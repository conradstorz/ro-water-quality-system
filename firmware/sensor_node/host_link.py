"""PlatformIO extra script: link settings for the PC build of the sensor node."""

Import("env")  # noqa: F821  (provided by SCons)

if env["PLATFORM"] == "win32":  # noqa: F821
    # Winsock for the host program; static so it starts whatever PATH holds.
    env.Append(LIBS=["ws2_32"], LINKFLAGS=["-static"])  # noqa: F821
