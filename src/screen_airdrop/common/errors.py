"""Error codes shared by sender and receiver."""

E1001 = "E1001"  # input path does not exist
E1002 = "E1002"  # packing failed
E1003 = "E1003"  # compression failed
E2001 = "E2001"  # roi locate failed
E2002 = "E2002"  # sync/calibration failed
E2003 = "E2003"  # header crc failed
E2004 = "E2004"  # payload crc failed
E3001 = "E3001"  # final sha mismatch
E3002 = "E3002"  # restore failed


class ScreenAirdropError(Exception):
    """Base exception with machine-readable code."""

    def __init__(self, code, message):
        super(ScreenAirdropError, self).__init__("{0}: {1}".format(code, message))
        self.code = code
        self.message = message
