// Minimal Modbus RTU server: functions 03 and 04 only (ADR-0007).
#pragma once

#include <cstddef>
#include <cstdint>

#include "ro_hal.hpp"
#include "ro_node.hpp"

namespace ro::node {

class RtuServer {
public:
    // A frame ends after `frame_gap_us` without a byte.
    RtuServer(const Node& node, ByteTransport& transport, Clock& clock,
              std::uint32_t frame_gap_us);

    // Take in received bytes and answer a completed frame. Never blocks beyond
    // what the transport's read does.
    void poll();

private:
    static constexpr std::size_t MAX_FRAME = 256;  // RTU ADU limit

    void handle_frame();
    void reply_registers(std::uint8_t function, std::uint16_t address, std::uint16_t count);
    void reply_exception(std::uint8_t function, std::uint8_t code);
    // Append the CRC to the first `size` bytes of reply_ and send it.
    void send(std::size_t size);

    const Node& node_;
    ByteTransport& transport_;
    Clock& clock_;
    std::uint32_t frame_gap_us_;
    std::uint8_t frame_[MAX_FRAME] = {};
    std::uint8_t reply_[MAX_FRAME] = {};
    std::size_t size_ = 0;
    bool overflow_ = false;
    std::uint32_t last_byte_us_ = 0;
};

}  // namespace ro::node
