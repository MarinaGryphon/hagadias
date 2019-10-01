"""Helper functions for Qud Blueprint Explorer."""

import os
import re
from ctypes import *

# load and store the Code Page 437 to Unicode translation
CP437_MAP_FILE = os.path.join(os.path.dirname(__file__), 'IBMGRAPH.TXT')
cp437_conv = {}
with open(CP437_MAP_FILE) as f:
    for line in f.readlines():
        if not line.startswith('#'):
            unicode, cp437, *_ = line.split()
            cp437_conv[int(cp437, base=16)] = chr(int(unicode, base=16))


def cp437_to_unicode(val: int):
    """Convert an IBM Code Page 437 code point to its Unicode equivalent.

    See https://stackoverflow.com/questions/46942721/is-cp437-decoding-broken-for-control-characters
    """
    if val > 0x1f:
        # no control characters, just ascii and "upper ascii"
        hex_val = hex(val)[2:]
        if len(hex_val) == 1:
            hex_val = '0' + hex_val
        byte = bytes.fromhex(hex_val)
        glyph = byte.decode(encoding='cp437')
    else:
        # control character - must be loaded from table
        glyph = cp437_conv[val]
    return glyph


# From https://stackoverflow.com/questions/580924/python-windows-file-version-attribute:

# returns the requested version information from the given file
#
# `language` should be an 8-character string combining both the language and
# codepage (such as "040904b0"); if None, the first language in the translation
# table is used instead
#
def get_dll_version_string(filename, what, language=None):
    # VerQueryValue() returns an array of that for VarFileInfo\Translation
    #
    class LANGANDCODEPAGE(Structure):
        _fields_ = [
            ("wLanguage", c_uint16),
            ("wCodePage", c_uint16)]

    wstr_file = wstring_at(filename)

    # getting the size in bytes of the file version info buffer
    size = windll.version.GetFileVersionInfoSizeW(wstr_file, None)
    if size == 0:
        raise WinError()

    buffer = create_string_buffer(size)

    # getting the file version info data
    if windll.version.GetFileVersionInfoW(wstr_file, None, size, buffer) == 0:
        raise WinError()

    # VerQueryValue() wants a pointer to a void* and DWORD; used both for
    # getting the default language (if necessary) and getting the actual data
    # below
    value = c_void_p(0)
    value_size = c_uint(0)

    if language is None:
        # file version information can contain much more than the version
        # number (copyright, application name, etc.) and these are all
        # translatable
        #
        # the following arbitrarily gets the first language and codepage from
        # the list
        ret = windll.version.VerQueryValueW(
            buffer, wstring_at(r"\VarFileInfo\Translation"),
            byref(value), byref(value_size))

        if ret == 0:
            raise WinError()

        # value points to a byte inside buffer, value_size is the size in bytes
        # of that particular section

        # casting the void* to a LANGANDCODEPAGE*
        lcp = cast(value, POINTER(LANGANDCODEPAGE))

        # formatting language and codepage to something like "040904b0"
        language = "{0:04x}{1:04x}".format(
            lcp.contents.wLanguage, lcp.contents.wCodePage)

    # getting the actual data
    res = windll.version.VerQueryValueW(
        buffer, wstring_at("\\StringFileInfo\\" + language + "\\" + what),
        byref(value), byref(value_size))

    if res == 0:
        raise WinError()

    # value points to a string of value_size characters, minus one for the
    # terminating null
    return wstring_at(value.value, value_size.value - 1)


class DiceBag:
    """Loads a dice string and provides methods to roll or analyze that string.

    Parameters:
        dice_string: a dice string, such as '1d4', '3d6+1-2d2', or '17'.
    """

    class Die:
        """Represents a single segment of a larger dice string. Numeric values are converted to dice
        rolls for simplicity - for example, '7' becomes '7d1'.

        Parameters:
            quantity: the number of times to roll the die (i.e. '2' if the die string is '2d6')
            size: the number of sides on the die (i.e. '6' if the die string is '2d6')
        """

        def __init__(self, quantity, size):
            self.quantity = quantity
            self.size = size

    # static regex patterns:
    # valid dice string must contain only 0-9, +, -, d, or spaces
    pattern_valid_dice = re.compile(r'[\d\sd+-]+')
    # any dice string segment, generally delimited by + or - (examples: 1d6, +3d2, -4)
    pattern_dice_segment = re.compile(r'[+-]?[^+-]+')
    # a dice string segment that includes 'd' and represents a die roll (examples: 2d3, -1d2)
    pattern_die_roll = re.compile(r'^([+-]?\d+)d(\d+)$')
    # a dice string segment that represents a numeric bonus or malus (examples: +3, -1)
    pattern_die_bonus = re.compile(r'^([+-]?\d+)$')

    def __init__(self, dice_string: str):
        if self.pattern_valid_dice.match(dice_string) is None:
            raise ValueError(f"Invalid string for DiceBag ({dice_string})"
                             " - dice string must contain only 0-9, +, -, d, or spaces")
        self.dice_bag = []
        dice_string = "".join(dice_string.split())  # strip all whitespace from dice_string
        dice_iter = self.pattern_dice_segment.finditer(dice_string)
        for die in dice_iter:
            m = self.pattern_die_roll.match(die.group(0))
            if m:
                self.dice_bag.append(DiceBag.Die(float(m.group(1)), float(m.group(2))))
            else:
                m = self.pattern_die_bonus.match(die.group(0))
                if m:
                    self.dice_bag.append(DiceBag.Die(float(m.group(1)), 1.0))
                else:
                    raise ValueError(f"DiceBag created with segment of unsupported format: {die}")

    def average(self):
        """Return the average value that is rolled from this dice string,
        rounded down to the nearest integer."""
        val = 0.0
        for die in self.dice_bag:
            val += die.quantity * (1.0 + die.size) / 2.0
        return int(val)

    def minimum(self):
        """Return the minimum value that can be rolled from this dice string."""
        val = 0.0
        for die in self.dice_bag:
            if die.quantity >= 0:
                val += die.quantity * 1
            else:
                val += die.quantity * die.size
        return int(val)

    def maximum(self):
        """Return the maximum value that can be rolled from this dice string."""
        val = 0.0
        for die in self.dice_bag:
            if die.quantity >= 0:
                val += die.quantity * die.size
            else:
                val += die.quantity * 1
        return int(val)

    def shake(self):
        """Simulate and return a random roll for this dice string."""
        from random import randrange
        val = 0
        for die in self.dice_bag:
            q = int(die.quantity)
            s = int(die.size)
            if q > 0:
                for i in range(q):
                    val += randrange(s) + 1
            elif q < 0:
                for i in range(abs(q)):
                    val -= randrange(s) + 1
        return val


