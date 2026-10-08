"""
dlms_core.py - UI-free DLMS/COSEM over TCP (WRAPPER) core.

Ported from All_object_hdlc_rev3.py (TCP/IP mode only). No Tkinter, no
serial, no reportlab/openpyxl, so it runs on Android (Kivy / python-for-android).
"""
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta

from gurux_dlms import GXDLMSClient, GXReplyData
from gurux_dlms.enums import (
    AccessMode,
    Authentication,
    DataType,
    ErrorCode,
    InterfaceType,
    ObjectType,
    Security,
)
from gurux_dlms.objects import GXDLMSData, GXDLMSAssociationLogicalName
from gurux_dlms.secure.GXDLMSSecureClient import GXDLMSSecureClient
from gurux_dlms.ValueEventArgs import ValueEventArgs

from obis_data import OBJECT_ATTRIBUTES, DEFAULT_ATTRIBUTES, OBIS_NAMES

# ─── ASSOCIATIONS (same values as the desktop tool) ─────────────────────────
ASSOCIATIONS = {
    "PC": dict(client_ae=16, server_ae=1, auth=Authentication.NONE,
               security=Security.NONE, password="",
               ic_obis=None),
    "MR": dict(client_ae=32, server_ae=1, auth=Authentication.HIGH,
               security=Security.ENCRYPTION, password="49534B5F53454331",
               ic_obis="0.0.43.1.2.255"),
    "US": dict(client_ae=48, server_ae=1, auth=Authentication.HIGH,
               security=Security.AUTHENTICATION_ENCRYPTION,
               password="49534B5F5345435245545F4153534333",
               ic_obis="0.0.43.1.3.255"),
    "PUSH": dict(client_ae=64, server_ae=1, auth=Authentication.NONE,
                 security=Security.ENCRYPTION, password="",
                 ic_obis="0.0.43.1.4.255"),
    "IHD": dict(client_ae=96, server_ae=1, auth=Authentication.LOW,
                security=Security.ENCRYPTION,
                password="49534B5F4948445F50415353574F5244",
                ic_obis="0.0.43.1.6.255"),
}
# NOTE: "FW" (firmware-upgrade) association is intentionally not ported.


@dataclass
class MeterConfig:
    host: str = "0000:0000:0000:0000:0000:0000:0000:0000"
    port: int = 4059
    association: str = "MR"
    hls_key: str = "49534B5F53454331"
    system_title: str = "49534B3030303031"
    auth_key: str = "000102030405060708090A0B0C0D0E0F"
    block_cipher_key: str = "000102030405060708090A0B0C0D0E0F"
    connect_timeout: float = 10.0
    reply_timeout: float = 8.0


def obis_name(obis):
    return OBIS_NAMES.get(obis, obis)


def attributes_for(obj):
    return OBJECT_ATTRIBUTES.get(obj.objectType, DEFAULT_ATTRIBUTES)


_WRITE_ACCESS_MODES = {
    AccessMode.WRITE,
    AccessMode.READ_WRITE,
    AccessMode.AUTHENTICATED_WRITE,
    AccessMode.AUTHENTICATED_READ_WRITE,
}
_WRITE_INTEGER_RANGES = {
    DataType.INT8: (-128, 127),
    DataType.INT16: (-32768, 32767),
    DataType.INT32: (-2147483648, 2147483647),
    DataType.INT64: (-9223372036854775808, 9223372036854775807),
    DataType.UINT8: (0, 255),
    DataType.UINT16: (0, 65535),
    DataType.UINT32: (0, 4294967295),
    DataType.UINT64: (0, 18446744073709551615),
    DataType.ENUM: (0, 255),
}
_WRITE_SCALAR_TYPES = set(_WRITE_INTEGER_RANGES) | {
    DataType.BOOLEAN,
    DataType.FLOAT32,
    DataType.FLOAT64,
    DataType.STRING,
    DataType.STRING_UTF8,
}


def writable_scalar_attributes(obj):
    result = []
    for index, name in attributes_for(obj):
        settings = obj.attributes.find(index)
        if settings is None or settings.access not in _WRITE_ACCESS_MODES:
            continue
        try:
            data_type = obj.getDataType(index)
        except (TypeError, ValueError):
            continue
        if data_type in _WRITE_SCALAR_TYPES:
            result.append((index, name))
    return result


def _parse_write_value(value, data_type):
    if data_type == DataType.BOOLEAN:
        normalized = value.strip().lower()
        if normalized not in ("true", "false"):
            raise ValueError("Enter true or false for a Boolean attribute")
        return normalized == "true"
    if data_type in _WRITE_INTEGER_RANGES:
        text = value.strip()
        parsed = int(text, 16 if text.lower().startswith(("0x", "+0x", "-0x")) else 10)
        lower, upper = _WRITE_INTEGER_RANGES[data_type]
        if not lower <= parsed <= upper:
            raise ValueError(f"Value must be between {lower} and {upper}")
        return parsed
    if data_type in (DataType.FLOAT32, DataType.FLOAT64):
        return float(value.strip())
    if data_type in (DataType.STRING, DataType.STRING_UTF8):
        return value
    raise ValueError(f"Writing {data_type.name} values is not supported")


# ─── VALUE FORMATTING (from _format_value / _fmt_cell) ──────────────────────
def _parse_dlms_datetime(data):
    if not isinstance(data, (bytearray, bytes)) or len(data) < 12:
        return None
    try:
        year = (data[0] << 8) | data[1]
        month, day = data[2], data[3]
        hour, minute, second = data[5], data[6], data[7]
        if month == 0xFF or day == 0xFF:
            return None
        return datetime(year, month, day, hour, minute, second).strftime(
            "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def fmt_cell(v):
    if v is None:
        return "-"
    if isinstance(v, (bytearray, bytes)):
        if len(v) == 12:
            parsed = _parse_dlms_datetime(v)
            if parsed:
                return parsed
        try:
            s = v.decode("utf-8").strip("\x00")
            if s == "*-*-* *:*:*":
                return "-"
            return s if s else v.hex().upper()
        except Exception:
            return v.hex().upper()
    if isinstance(v, str):
        return "-" if v.strip() == "*-*-* *:*:*" else v
    if hasattr(v, "dateTime") and v.dateTime is not None:
        try:
            return v.dateTime.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(v)
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(v)
    if hasattr(v, "value"):
        return fmt_cell(v.value)
    if isinstance(v, list):
        return " | ".join(fmt_cell(x) for x in v)
    return str(v)


def format_value(raw):
    if raw is None:
        return "-"
    if isinstance(raw, (bytearray, bytes)):
        try:
            return raw.decode("utf-8").strip("\x00")
        except Exception:
            return raw.hex().upper()
    if isinstance(raw, list):
        if len(raw) == 0:
            return "[ ]"
        if len(raw) == 2 and all(isinstance(x, int) for x in raw):
            return f"Scaler: {raw[0]}  Unit: {raw[1]}"
        parts = [format_value(i) for i in raw[:20]]
        suffix = f"  ... (+{len(raw) - 20} more)" if len(raw) > 20 else ""
        return "[" + ",  ".join(parts) + "]" + suffix
    if hasattr(raw, "value"):
        return format_value(raw.value)
    return str(raw)


# ─── TCP TRANSPORT ───────────────────────────────────────────────────────────
class TcpTransport:
    """TCP socket carrying DLMS WRAPPER PDUs (8-byte header: ver, src, dst, len)."""

    def __init__(self, cfg: MeterConfig, log=None):
        self.cfg = cfg
        self.log = log or (lambda *a, **k: None)
        family = socket.AF_INET6 if ":" in cfg.host else socket.AF_INET
        self.sock = socket.socket(family, socket.SOCK_STREAM)
        self.sock.settimeout(cfg.connect_timeout)
        self.sock.connect((cfg.host, int(cfg.port)))
        self.sock.settimeout(cfg.reply_timeout)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Meter closed the connection")
            buf += chunk
        return buf

    def _recv_pdu(self):
        """Read exactly one WRAPPER PDU (robust against TCP segmentation)."""
        header = self._recv_exact(8)
        if header[0] == 0x00 and header[1] == 0x01:
            length = (header[6] << 8) | header[7]
            return header + self._recv_exact(length)
        # Not a WRAPPER header: return whatever else is available.
        try:
            self.sock.settimeout(0.5)
            return header + self.sock.recv(4096)
        except socket.timeout:
            return header
        finally:
            self.sock.settimeout(self.cfg.reply_timeout)

    def _send(self, data):
        packets = data if isinstance(data, list) else [data]
        for pkt in packets:
            self.log("TX " + bytes(pkt).hex().upper())
            self.sock.sendall(pkt)

    def send_receive(self, client, data, reply):
        if data is None:
            return reply
        self._send(data)
        buf = self._recv_pdu()
        self.log("RX " + buf.hex().upper())
        client.getData(buf, reply)
        guard = 0
        while reply.isMoreData() and guard < 5000:
            guard += 1
            nxt = client.receiverReady(reply.moreData)
            if nxt is None:
                break
            self._send(nxt)
            buf = self._recv_pdu()
            self.log("RX " + buf.hex().upper())
            client.getData(buf, reply)
        return reply


# ─── SESSION ─────────────────────────────────────────────────────────────────
class MeterSession:
    """Context manager: connect -> AARQ (+HLS) -> yield -> release -> close."""

    def __init__(self, cfg: MeterConfig, log=None):
        self.cfg = cfg
        self.log = log or (lambda *a, **k: None)
        self.assoc = ASSOCIATIONS.get(cfg.association, ASSOCIATIONS["MR"])
        self.client = None
        self.transport = None

    # -- invocation counter (read through the PC / public association) --
    def _read_invocation_counter(self):
        ic_obis = self.assoc.get("ic_obis")
        if not ic_obis:
            return 0
        client = GXDLMSClient(True)
        client.interfaceType = InterfaceType.WRAPPER
        client.clientAddress = 16
        client.serverAddress = 1
        client.authentication = Authentication.NONE
        transport = None
        try:
            transport = TcpTransport(self.cfg, self.log)
            reply = GXReplyData()
            transport.send_receive(client, client.aarqRequest(), reply)
            client.parseAareResponse(reply.data)
            ic_obj = GXDLMSData(ic_obis)
            reply.clear()
            req = client.read(ic_obj, 2)
            if not req:
                return 0
            for pkt in (req if isinstance(req, list) else [req]):
                transport.send_receive(client, pkt, reply)
            client.updateValue(ic_obj, 2, reply.value)
            ic = int(ic_obj.value) if ic_obj.value else 0
            self.log(f"Invocation counter = {ic}")
            return ic
        except Exception as e:
            self.log(f"Could not read invocation counter: {e}")
            return 0
        finally:
            if transport:
                try:
                    rel = client.disconnectRequest()
                    if rel:
                        transport.send_receive(client, rel, GXReplyData())
                except Exception:
                    pass
                transport.close()

    def _build_client(self, ic):
        a = self.assoc
        if a["auth"] == Authentication.NONE and a["security"] == Security.NONE:
            c = GXDLMSClient(True)
            c.interfaceType = InterfaceType.WRAPPER
            c.clientAddress = a["client_ae"]
            c.serverAddress = a["server_ae"]
            c.authentication = Authentication.NONE
            return c
        c = GXDLMSSecureClient(True)
        c.interfaceType = InterfaceType.WRAPPER
        c.clientAddress = a["client_ae"]
        c.serverAddress = a["server_ae"]
        c.authentication = a["auth"]
        password = self.cfg.hls_key if self.cfg.association == "MR" else a["password"]
        if password:
            c.password = bytes.fromhex(password)
        c.ciphering.security = a["security"]
        c.ciphering.systemTitle = bytes.fromhex(self.cfg.system_title)
        c.ciphering.authenticationKey = bytes.fromhex(self.cfg.auth_key)
        c.ciphering.blockCipherKey = bytes.fromhex(self.cfg.block_cipher_key)
        c.ciphering.invocationCounter = ic + 1
        return c

    def open(self):
        a = self.assoc
        ic = 0
        if a["auth"] != Authentication.NONE and a.get("ic_obis"):
            ic = self._read_invocation_counter()
        self.client = self._build_client(ic)
        self.transport = TcpTransport(self.cfg, self.log)

        reply = GXReplyData()
        aarq = self.client.aarqRequest()
        if not aarq:
            raise RuntimeError("Failed to build AARQ")
        self.transport.send_receive(self.client, aarq, reply)
        if not reply.data:
            raise RuntimeError("Empty AARE from meter")
        self.client.parseAareResponse(reply.data)

        if a["auth"] == Authentication.HIGH:
            reply.clear()
            for pkt in self.client.getApplicationAssociationRequest():
                self.transport.send_receive(self.client, pkt, reply)
            self.client.parseApplicationAssociationResponse(reply.data)
        self.log(f"Connected ({self.cfg.association} association)")
        return self

    def close(self):
        if self.client and self.transport:
            try:
                rel = self.client.disconnectRequest()
                if rel:
                    self.transport.send_receive(self.client, rel, GXReplyData())
            except Exception:
                pass
        if self.transport:
            self.transport.close()
        self.client = self.transport = None

    def __enter__(self):
        try:
            return self.open()
        except Exception:
            self.close()
            raise

    def __exit__(self, *exc):
        self.close()

    # -- generic helpers --
    def _run(self, req, reply=None):
        reply = reply or GXReplyData()
        for pkt in (req if isinstance(req, list) else [req]):
            self.transport.send_receive(self.client, pkt, reply)
        return reply

    def read_attribute(self, obj, attr_idx):
        req = self.client.read(obj, attr_idx)
        if not req:
            return "-"
        reply = self._run(req)
        self.client.updateValue(obj, attr_idx, reply.value)
        return format_value(reply.value)

    def write_attribute(self, obj, attr_idx, value):
        if self.client is None or self.transport is None:
            raise RuntimeError("Meter session is not open")
        settings = obj.attributes.find(attr_idx)
        if settings is None or settings.access not in _WRITE_ACCESS_MODES:
            raise PermissionError("Meter did not report write access for this attribute")

        data_type = obj.getDataType(attr_idx)
        if data_type not in _WRITE_SCALAR_TYPES:
            raise ValueError(f"Writing {data_type.name} values is not supported")
        parsed_value = _parse_write_value(value, data_type)
        event = ValueEventArgs(self.client.settings, obj, attr_idx)
        old_value = obj.getValue(self.client.settings, event)
        event.value = parsed_value
        obj.setValue(self.client.settings, event)
        if event.error != ErrorCode.OK:
            event.value = old_value
            obj.setValue(self.client.settings, event)
            raise PermissionError("Gurux rejected the local attribute update")

        try:
            reply = self._run(self.client.write(obj, attr_idx))
            if reply.error != ErrorCode.OK:
                try:
                    error = ErrorCode(reply.error)
                    error_name = error.name
                except (TypeError, ValueError):
                    error = None
                    error_name = str(reply.error)
                if error == ErrorCode.UNMATCHED_TYPE:
                    raise RuntimeError(
                        f"Meter rejected DLMS type {data_type.name} for "
                        f"{obj.logicalName} attribute {attr_idx} "
                        "(UNMATCHED_TYPE, 12). Verify the attribute's expected type."
                    )
                raise RuntimeError(f"DLMS write failed: {error_name} ({reply.error})")
        except Exception:
            event.value = old_value
            obj.setValue(self.client.settings, event)
            raise
        return format_value(parsed_value)

    def read_object_list(self):
        assoc = GXDLMSAssociationLogicalName("0.0.40.0.0.255")
        reply = self._run(self.client.read(assoc, 2))
        self.client.updateValue(assoc, 2, reply.value)
        return list(assoc.objectList)

    def read_profile(self, obj, mode="last", count=10, days=1):
        """mode: 'last' (N entries), 'days' (last N days), 'all'.
        Returns (column_names, rows) where rows are lists of strings."""
        reply3 = self._run(self.client.read(obj, 3))
        self.client.updateValue(obj, 3, reply3.value)
        cols = []
        if getattr(obj, "captureObjects", None):
            for co, _ci in obj.captureObjects:
                cols.append(obis_name(co.logicalName))

        if mode == "last":
            try:
                pkts = self.client.readRowsByEntry(obj, 1, max(1, int(count)))
            except Exception:
                pkts = self.client.read(obj, 2)
        elif mode == "days":
            end = datetime.now()
            start = end - timedelta(days=max(0, int(days)))
            try:
                pkts = self.client.readRowsByRange(obj, start, end, [])
            except Exception:
                pkts = self.client.read(obj, 2)
        else:
            pkts = self.client.read(obj, 2)

        reply = self._run(pkts)
        raw = reply.value
        try:
            self.client.updateValue(obj, 2, raw)
            if getattr(obj, "buffer", None):
                raw = obj.buffer
        except Exception:
            pass
        rows = []
        for row in (raw or []):
            row = list(row) if not isinstance(row, list) else row
            rows.append([fmt_cell(v) for v in row])
        return cols, rows


def object_type_name(obj):
    return ObjectType(obj.objectType).name.replace("_", " ").title()
