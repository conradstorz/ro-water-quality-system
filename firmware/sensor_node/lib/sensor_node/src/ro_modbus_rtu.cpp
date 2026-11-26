#include "ro_modbus_rtu.hpp"

namespace ro::node {

namespace {

constexpr std::uint8_t READ_HOLDING = 0x03;
constexpr std::uint8_t READ_INPUT = 0x04;
constexpr std::uint8_t EXCEPTION_FLAG = 0x80;
constexpr std::uint8_t ILLEGAL_FUNCTION = 0x01;
constexpr std::uint8_t ILLEGAL_DATA_ADDRESS = 0x02;
constexpr std::uint8_t ILLEGAL_DATA_VALUE = 0x03;
constexpr std::uint16_t MAX_READ = 125;
constexpr std::size_t MIN_FRAME = 4;      // unit, function, CRC
constexpr std::size_t READ_REQUEST = 8;   // unit, function, address, count, CRC

std::uint16_t crc16(const std::uint8_t* data, std::size_t size) {
    std::uint16_t crc = 0xFFFF;
    for (std::size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) {
            crc = (crc & 1u) ? static_cast<std::uint16_t>((crc >> 1) ^ 0xA001)
                             : static_cast<std::uint16_t>(crc >> 1);
        }
    }
    return crc;
}

std::uint16_t big_endian(const std::uint8_t* data) {
    return static_cast<std::uint16_t>((data[0] << 8) | data[1]);
}

}  // namespace

RtuServer::RtuServer(const Node& node, ByteTransport& transport, Clock& clock,
                     std::uint32_t frame_gap_us)
    : node_(node), transport_(transport), clock_(clock), frame_gap_us_(frame_gap_us) {}

void RtuServer::poll() {
    std::uint8_t chunk[64];
    const std::size_t received = transport_.read(chunk, sizeof(chunk));
    const std::uint32_t now = clock_.now_us();
    // Close a finished frame before taking in new bytes: a late poll can find
    // the next frame already waiting. Unsigned subtraction survives clock wrap.
    if (size_ > 0 && now - last_byte_us_ >= frame_gap_us_) {
        if (!overflow_) {
            handle_frame();
        }
        size_ = 0;
        overflow_ = false;
    }
    for (std::size_t i = 0; i < received; ++i) {
        if (size_ < MAX_FRAME) {
            frame_[size_++] = chunk[i];
        } else {
            overflow_ = true;  // discard the whole burst
        }
    }
    if (received > 0) {
        last_byte_us_ = now;
    }
}

void RtuServer::handle_frame() {
    // No reply to: an unconfigured node, a runt, a bad CRC, another unit.
    if (node_.unit_id() == 0 || size_ < MIN_FRAME) {
        return;
    }
    const std::uint16_t crc =
        static_cast<std::uint16_t>(frame_[size_ - 2] | (frame_[size_ - 1] << 8));
    if (crc != crc16(frame_, size_ - 2) || frame_[0] != node_.unit_id()) {
        return;
    }
    const std::uint8_t function = frame_[1];
    if (function & EXCEPTION_FLAG) {
        return;  // an exception reply, not a request
    }
    if (function != READ_HOLDING && function != READ_INPUT) {
        reply_exception(function, ILLEGAL_FUNCTION);
        return;
    }
    if (size_ != READ_REQUEST) {
        reply_exception(function, ILLEGAL_DATA_VALUE);
        return;
    }
    const std::uint16_t address = big_endian(&frame_[2]);
    const std::uint16_t count = big_endian(&frame_[4]);
    if (count < 1 || count > MAX_READ) {
        reply_exception(function, ILLEGAL_DATA_VALUE);
        return;
    }
    reply_registers(function, address, count);
}

void RtuServer::reply_registers(std::uint8_t function, std::uint16_t address,
                                std::uint16_t count) {
    std::uint16_t inputs[reg::INPUT_COUNT];
    std::uint16_t metadata[reg::METADATA_COUNT];
    const bool input = function == READ_INPUT;
    const std::uint32_t start = input ? reg::INPUT_START : reg::METADATA_START;
    const std::uint32_t size = input ? reg::INPUT_COUNT : reg::METADATA_COUNT;
    if (address < start || static_cast<std::uint32_t>(address) + count > start + size) {
        reply_exception(function, ILLEGAL_DATA_ADDRESS);
        return;
    }
    const std::uint16_t* block = metadata;
    if (input) {
        node_.copy_input_registers(inputs);
        block = inputs;
    } else {
        node_.copy_metadata(metadata);
    }
    reply_[0] = node_.unit_id();
    reply_[1] = function;
    reply_[2] = static_cast<std::uint8_t>(2 * count);
    std::size_t length = 3;
    for (std::uint32_t i = 0; i < count; ++i) {
        const std::uint16_t word = block[address - start + i];
        reply_[length++] = static_cast<std::uint8_t>(word >> 8);
        reply_[length++] = static_cast<std::uint8_t>(word & 0xFF);
    }
    send(length);
}

void RtuServer::reply_exception(std::uint8_t function, std::uint8_t code) {
    reply_[0] = node_.unit_id();
    reply_[1] = static_cast<std::uint8_t>(function | EXCEPTION_FLAG);
    reply_[2] = code;
    send(3);
}

void RtuServer::send(std::size_t size) {
    const std::uint16_t crc = crc16(reply_, size);
    reply_[size] = static_cast<std::uint8_t>(crc & 0xFF);  // CRC goes low byte first
    reply_[size + 1] = static_cast<std::uint8_t>(crc >> 8);
    transport_.write(reply_, size + 2);
}

}  // namespace ro::node
