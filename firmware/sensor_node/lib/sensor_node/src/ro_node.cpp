#include "ro_node.hpp"

#include <cstring>

namespace ro::node {

namespace {

constexpr std::uint8_t MAX_UNIT_ID = 15;  // four jumpers: unit ids 1-15

// An out-of-range value is not truncated into another node's id: it gives 0.
std::uint8_t unit_id_from(std::uint8_t linked_mask) {
    return linked_mask <= MAX_UNIT_ID ? linked_mask : 0;
}

}  // namespace

Node::Node(NodeIdInputs& id_inputs) : unit_id_(unit_id_from(id_inputs.linked_mask())) {
    publish(reg::Snapshot{}, false);
}

void Node::commit(const reg::Snapshot& acquired) {
    ++sequence_;  // modulo 65536
    publish(acquired, true);
}

void Node::publish(reg::Snapshot snapshot, bool committed) {
    snapshot.protocol_major = reg::PROTOCOL_MAJOR;
    snapshot.protocol_minor = PROTOCOL_MINOR;
    snapshot.snapshot_sequence = sequence_;
    snapshot.node_type = static_cast<std::uint16_t>(NODE_TYPE);
    snapshot.installed_mask = INSTALLED_MASK;
    snapshot.validity_mask &= INSTALLED_MASK;
    if ((INSTALLED_MASK & reg::CRITICAL_VALIDITY) == 0) {
        snapshot.critical_age_ms = NO_CRITICAL_AGE_MS;
    }
    snapshot.module_status &= static_cast<std::uint16_t>(~reg::status_bits::OPERATIONAL);
    if (committed && unit_id_ != 0) {
        snapshot.module_status |= reg::status_bits::OPERATIONAL;
    }
    snapshot.sensor_error_code = 0;  // code table TBD (Modbus spec section 5)

    const std::uint8_t back = front_ ^ 1u;
    reg::encode_snapshot(snapshot, buffers_[back]);
    front_ = back;
}

void Node::copy_input_registers(std::uint16_t (&words)[reg::INPUT_COUNT]) const {
    std::memcpy(words, buffers_[front_], sizeof(words));
}

void Node::copy_metadata(std::uint16_t (&words)[reg::METADATA_COUNT]) const {
    reg::Metadata metadata;
    metadata.configuration_schema_version = CONFIGURATION_SCHEMA_VERSION;
    metadata.calibration_revision = CALIBRATION_REVISION;
    metadata.device_id = DEVICE_ID;
    reg::encode_metadata(metadata, words);
}

}  // namespace ro::node
