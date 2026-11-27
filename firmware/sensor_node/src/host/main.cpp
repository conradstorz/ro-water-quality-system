// The sensor node as a PC program: the real node logic with fake hardware, its
// "UART" being a TCP socket carrying Modbus RTU frames. Test tool only.
//
// Usage: program [--id-jumpers MASK] [--no-commit] [--set FIELD=VALUE]... [--stall-ms N]
//   --id-jumpers  fake jumper links, bit n = NODE_ID_n (default 0: none)
//   --no-commit   test only: serve without the boot-time snapshot commit
//   --set         test only: value of a field in the snapshot handed to commit()
//   --stall-ms    test only: be busy this long after receiving, so the next poll is late
// Prints "PORT n" once it is listening on 127.0.0.1.

#ifdef _WIN32
#include <winsock2.h>
#else
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>

#include "ro_modbus_rtu.hpp"
#include "ro_node.hpp"

namespace {

#ifdef _WIN32
using Socket = SOCKET;
using Length = int;
void close_socket(Socket s) { closesocket(s); }
#else
using Socket = int;
using Length = socklen_t;
constexpr Socket INVALID_SOCKET = -1;
void close_socket(Socket s) { close(s); }
#endif

// Loopback has no line timing, so the frame gap is generous compared with the
// 3.5 characters of a real bus, to ride out host scheduling jitter.
constexpr std::uint32_t HOST_FRAME_GAP_US = 20000;

class SocketTransport final : public ro::node::ByteTransport {
public:
    explicit SocketTransport(Socket socket) : socket_(socket) {}

    bool open() const { return open_; }

    // Whether read() has returned bytes since the last call.
    bool take_received() {
        const bool received = received_;
        received_ = false;
        return received;
    }

    std::size_t read(std::uint8_t* buffer, std::size_t capacity) override {
        fd_set readable;
        FD_ZERO(&readable);
        FD_SET(socket_, &readable);
        timeval timeout{0, 1000};
        if (select(static_cast<int>(socket_) + 1, &readable, nullptr, nullptr, &timeout) <= 0) {
            return 0;
        }
        const auto received = recv(socket_, reinterpret_cast<char*>(buffer),
                                   static_cast<int>(capacity), 0);
        if (received <= 0) {
            open_ = false;
            return 0;
        }
        received_ = true;
        return static_cast<std::size_t>(received);
    }

    void write(const std::uint8_t* data, std::size_t size) override {
        if (send(socket_, reinterpret_cast<const char*>(data), static_cast<int>(size), 0) < 0) {
            open_ = false;
        }
    }

private:
    Socket socket_;
    bool open_ = true;
    bool received_ = false;
};

class HostClock final : public ro::node::Clock {
public:
    std::uint32_t now_us() override {
        const auto since = std::chrono::steady_clock::now().time_since_epoch();
        return static_cast<std::uint32_t>(
            std::chrono::duration_cast<std::chrono::microseconds>(since).count());
    }
};

class FakeNodeIdInputs final : public ro::node::NodeIdInputs {
public:
    explicit FakeNodeIdInputs(std::uint8_t mask) : mask_(mask) {}
    std::uint8_t linked_mask() override { return mask_; }

private:
    std::uint8_t mask_;
};

// Only the fields the tests drive: one of each signed and 32-bit kind, and the
// node-owned fields, to show that commit() replaces them.
bool set_field(ro::reg::Snapshot& snapshot, const char* assignment) {
    const char* equals = std::strchr(assignment, '=');
    if (equals == nullptr) {
        return false;
    }
    const std::size_t length = static_cast<std::size_t>(equals - assignment);
    const long long value = std::strtoll(equals + 1, nullptr, 0);
    const auto is = [&](const char* name) {
        return std::strlen(name) == length && std::strncmp(assignment, name, length) == 0;
    };
    if (is("permeate_temp_c_x100")) {
        snapshot.permeate_temp_c_x100 = static_cast<std::int16_t>(value);
    } else if (is("load_left_raw")) {
        snapshot.load_left_raw = static_cast<std::int32_t>(value);
    } else if (is("permeate_total_pulses")) {
        snapshot.permeate_total_pulses = static_cast<std::uint32_t>(value);
    } else if (is("protocol_major")) {
        snapshot.protocol_major = static_cast<std::uint16_t>(value);
    } else if (is("protocol_minor")) {
        snapshot.protocol_minor = static_cast<std::uint16_t>(value);
    } else if (is("snapshot_sequence")) {
        snapshot.snapshot_sequence = static_cast<std::uint16_t>(value);
    } else if (is("validity_mask")) {
        snapshot.validity_mask = static_cast<std::uint16_t>(value);
    } else if (is("critical_age_ms")) {
        snapshot.critical_age_ms = static_cast<std::uint16_t>(value);
    } else if (is("sensor_error_code")) {
        snapshot.sensor_error_code = static_cast<std::uint16_t>(value);
    } else if (is("node_type")) {
        snapshot.node_type = static_cast<std::uint16_t>(value);
    } else if (is("installed_mask")) {
        snapshot.installed_mask = static_cast<std::uint16_t>(value);
    } else {
        return false;
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    std::uint8_t jumpers = 0;
    bool commit = true;
    unsigned long stall_ms = 0;
    ro::reg::Snapshot acquired;  // no sensors yet
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--no-commit") == 0) {
            commit = false;
        } else if (std::strcmp(argv[i], "--id-jumpers") == 0 && i + 1 < argc) {
            jumpers = static_cast<std::uint8_t>(std::strtoul(argv[++i], nullptr, 0));
        } else if (std::strcmp(argv[i], "--stall-ms") == 0 && i + 1 < argc) {
            stall_ms = std::strtoul(argv[++i], nullptr, 0);
        } else if (std::strcmp(argv[i], "--set") == 0 && i + 1 < argc &&
                   set_field(acquired, argv[i + 1])) {
            ++i;
        } else {
            std::fprintf(stderr, "bad argument: %s\n", argv[i]);
            return 2;
        }
    }

#ifdef _WIN32
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        std::fprintf(stderr, "WSAStartup failed\n");
        return 1;
    }
#endif

    FakeNodeIdInputs id_inputs(jumpers);
    HostClock clock;
    ro::node::Node node(id_inputs);
    if (commit) {
        // The boot-time commit of an empty snapshot: there are no sensors yet.
        // Issue #14 must replace this with commits of real acquisitions. Do not
        // repeat it on a timer: sequence advances only on new acquisitions.
        node.commit(acquired);
    }

    const Socket listener = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = 0;  // any free port
    Length length = sizeof(address);
    if (listener == INVALID_SOCKET ||
        bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0 ||
        listen(listener, 1) != 0 ||
        getsockname(listener, reinterpret_cast<sockaddr*>(&address), &length) != 0) {
        std::fprintf(stderr, "cannot listen on 127.0.0.1\n");
        return 1;
    }
    std::printf("PORT %u\n", static_cast<unsigned>(ntohs(address.sin_port)));
    std::fflush(stdout);

    // One master at a time, as on the bus. Runs until killed.
    for (;;) {
        const Socket connection = accept(listener, nullptr, nullptr);
        if (connection == INVALID_SOCKET) {
            close_socket(listener);
            return 1;
        }
        SocketTransport transport(connection);
        ro::node::RtuServer server(node, transport, clock, HOST_FRAME_GAP_US);
        while (transport.open()) {
            server.poll();
            if (transport.take_received() && stall_ms > 0) {
                std::this_thread::sleep_for(std::chrono::milliseconds(stall_ms));
            }
        }
        close_socket(connection);
    }
}
