// Node identity, health and the published register snapshot.
//
// Single-threaded: commit() and the copy functions must not run concurrently.
// A target that acquires and serves in separate tasks has to add a lock.
#pragma once

#include <cstdint>

#include "ro_hal.hpp"
#include "ro_registers.hpp"

namespace ro::node {

// Node capabilities. These describe this firmware, not the newest register map.
constexpr std::uint16_t PROTOCOL_MINOR = 3;  // 1.3: no 1-Wire name table (1.4)
static_assert(reg::PROTOCOL_MAJOR == 1 && reg::PROTOCOL_MINOR >= PROTOCOL_MINOR,
              "register map no longer covers the protocol this node implements");
constexpr reg::NodeType NODE_TYPE = reg::NodeType::RO_SKID;
constexpr std::uint16_t INSTALLED_MASK = 0;  // no process channel is fitted

// critical_age_ms of a node with no critical channel fitted (Modbus spec
// section 5). Not in the register map, so not generated.
constexpr std::uint16_t NO_CRITICAL_AGE_MS = 65535;

// Holding 200-202. The register map names these but defines no values; they
// match the simulator. Not protocol versions.
constexpr std::uint16_t CONFIGURATION_SCHEMA_VERSION = 1;
constexpr std::uint16_t CALIBRATION_REVISION = 0;  // no calibration store
constexpr std::uint16_t DEVICE_ID = 1;

class Node {
public:
    // Reads the ID jumpers once, as at boot.
    explicit Node(NodeIdInputs& id_inputs);

    // 1-15, or 0 for a node with no ID link or an out-of-range one, which must
    // stay silent.
    std::uint8_t unit_id() const { return unit_id_; }

    // Publish newly acquired channel values and advance snapshot_sequence.
    // Identity, version, sequence, validity limits and health fields are the
    // node's own; whatever `acquired` holds for them is replaced.
    void commit(const reg::Snapshot& acquired);

    // Copy the whole published snapshot, so one reply holds one commit.
    void copy_input_registers(std::uint16_t (&words)[reg::INPUT_COUNT]) const;
    void copy_metadata(std::uint16_t (&words)[reg::METADATA_COUNT]) const;

private:
    void publish(reg::Snapshot snapshot, bool committed);

    std::uint8_t unit_id_;
    std::uint16_t sequence_ = 0;
    // Double buffer: publish() fills the back one, then flips.
    std::uint16_t buffers_[2][reg::INPUT_COUNT] = {};
    std::uint8_t front_ = 0;
};

}  // namespace ro::node
