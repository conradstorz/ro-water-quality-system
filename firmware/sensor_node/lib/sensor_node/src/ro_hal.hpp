// Hardware interfaces of the sensor node. The node logic reaches hardware only
// through these; the PC build and the ESP32 build each supply implementations.
#pragma once

#include <cstddef>
#include <cstdint>

namespace ro::node {

// The serial link to the bus. Transmit direction control, if the transceiver
// needs it, belongs inside the implementation.
class ByteTransport {
public:
    // Return up to `capacity` received bytes without waiting long; 0 if none.
    virtual std::size_t read(std::uint8_t* buffer, std::size_t capacity) = 0;
    virtual void write(const std::uint8_t* data, std::size_t size) = 0;

protected:
    ~ByteTransport() = default;
};

// Free-running microsecond clock; wraps at 2^32.
class Clock {
public:
    virtual std::uint32_t now_us() = 0;

protected:
    ~Clock() = default;
};

// The hardwired node-ID jumpers.
class NodeIdInputs {
public:
    // Bit n is set when jumper NODE_ID_n links its input to ground
    // (hardware/sensor-node/pinout.yaml). The inputs are active low; the
    // implementation does the inversion.
    virtual std::uint8_t linked_mask() = 0;

protected:
    ~NodeIdInputs() = default;
};

}  // namespace ro::node
