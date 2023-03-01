import os
import sys
from time import time

from twisted.internet import defer, reactor, stdio
from twisted.protocols import basic
from quarry.net.auth import OfflineProfile
from quarry.net.client import ClientFactory, SpawningClientProtocol

message = input("Enter chat input: ")

class StdioProtocol(basic.LineReceiver):
    delimiter = os.linesep.encode('ascii')
    in_encoding  = getattr(sys.stdin,  "encoding", 'utf8')
    out_encoding = getattr(sys.stdout, "encoding", 'utf8')

    def lineReceived(self, line):
        self.minecraft_protocol.send_chat(line.decode(self.in_encoding))

    def send_line(self, text):
        self.sendLine(text.encode(self.out_encoding))


class MinecraftProtocol(SpawningClientProtocol):
    spawned = False

    # 1.19+
    def packet_system_message(self, buff):
        p_text = buff.unpack_chat().to_string()
        p_display = False

        # Ignore game info (action bar) messages
        if self.protocol_version >= 760:
            p_display = not buff.unpack('?')  # Boolean for whether message is game info
        else:
            p_display = buff.unpack_varint() != 2  # Varint for position where 2 is game info

        buff.discard()

        if p_display and p_text.strip():
            self.stdio_protocol.send_line(":: %s" % p_text)

    def packet_chat_message(self, buff):
        # 1.19.1+
        if self.protocol_version >= 760:
            p_signed_message = buff.unpack_signed_message()
            buff.unpack_varint()  # Filter result
            p_position = buff.unpack_varint()
            p_sender_name = buff.unpack_chat()

            buff.discard()

            if p_position not in (1, 2):  # Ignore system and game info messages
                # Sender name is sent separately to the message text
                self.stdio_protocol.send_line(
                    ":: <%s> %s" % (p_sender_name, p_signed_message.unsigned_content or p_signed_message.body.message))

            return

        p_text = buff.unpack_chat().to_string()

        # 1.19+
        if self.protocol_version == 759:
            p_unsigned_text = buff.unpack_optional(lambda: buff.unpack_chat().to_string())
            p_position = buff.unpack_varint()
            buff.unpack_uuid()  # Sender UUID
            p_sender_name = buff.unpack_chat()
            buff.discard()

            if p_position not in (1, 2):  # Ignore system and game info messages
                # Sender name is sent separately to the message text
                self.stdio_protocol.send_line("<%s> %s" % (p_sender_name, p_unsigned_text or p_text))

        elif self.protocol_version >= 47:  # 1.8.x+
            p_position = buff.unpack('B')
            buff.discard()

            if p_position not in (1, 2) and p_text.strip():  # Ignore system and game info messages
                self.stdio_protocol.send_line(p_text)

        elif p_text.strip():
            self.stdio_protocol.send_line(p_text)

    def send_chat(self, text):
        data = [self.buff_type.pack_string(text)]

        # 1.19+, add empty signature
        if self.protocol_version >= 759:
            data.append(self.buff_type.pack('QQ', int(time() * 1000), 0))   # Current timestamp, empty salt
            data.append(self.buff_type.pack_byte_array(b''))  # Empty signature
            data.append(self.buff_type.pack('?', False))  # Not previewed

        # 1.19.1+,
        if self.protocol_version >= 760:
            data.append(self.buff_type.pack_last_seen_list([]))  # Add empty last seen list
            data.append(self.buff_type.pack('?', False))  # Don't provide optional last received message

        self.send_packet(message, *data)


class MinecraftFactory(ClientFactory):
    protocol = MinecraftProtocol
    log_level = "WARN"

    def buildProtocol(self, addr):
        minecraft_protocol = super(MinecraftFactory, self).buildProtocol(addr)
        stdio_protocol = StdioProtocol()

        minecraft_protocol.stdio_protocol = stdio_protocol
        stdio_protocol.minecraft_protocol = minecraft_protocol

        stdio.StandardIO(stdio_protocol)
        return minecraft_protocol


@defer.inlineCallbacks
def main():
    username = input("Enter bot username: ")
    ip = input("Enter server IP address: ")
    print("logging in...")
    profile = OfflineProfile(username)
    factory = MinecraftFactory(profile)
    print("connecting...")
    factory = yield factory.connect(ip, 25565)
    print("connected!")


if __name__ == "__main__":
    main()
    try:
        reactor.run()
    except:
        print("An error happened!")
