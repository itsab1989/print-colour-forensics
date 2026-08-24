"""Normalise a vendor print stream so two runs of the same job can be compared.

Written against one inkjet driver family whose stream carries an XML preamble
(job GUID + datetime). Other vendors use other nonces -- ADD THEM HERE and
re-run the determinism control until repeats are byte-identical.

WHAT IT PROVES: with the nonces masked, the vendor filter's output is
byte-deterministic, so ANY remaining difference between two runs is caused by
the job options you changed — not by the clock or a session id.

WHAT IT CANNOT PROVE: what the bytes mean. This is a differential instrument:
"the colour engine reacted" / "it did not". It does not decode ink amounts.

POSITIVE CONTROL (mandatory): run the SAME option set >=2 times and assert the
normalised streams are identical. If they are not, there is another nonce and
every comparison below is worthless. Two were found in the driver family this was written against:
  * a CDATA job GUID          (8-4-4-4-12 uppercase hex)
  * <ivec:datetime>YYYYMMDDhhmmss</ivec:datetime>
"""
from __future__ import annotations
import re

_NONCES = (
    (re.compile(rb'[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}'), b'X' * 36),
    (re.compile(rb'(<ivec:datetime>)\d{14}(</ivec:datetime>)'), rb'\g<1>00000000000000\g<2>'),
)

def normalise(data: bytes) -> bytes:
    for pat, rep in _NONCES:
        data = pat.sub(rep, data)
    return data

def compare(a: bytes, b: bytes) -> dict:
    A, B = normalise(a), normalise(b)
    if A == B:
        return {"identical": True, "n_diff": 0, "first": None, "last": None,
                "len_a": len(A), "len_b": len(B)}
    d = [i for i in range(min(len(A), len(B))) if A[i] != B[i]]
    return {"identical": False, "n_diff": len(d) + abs(len(A) - len(B)),
            "first": d[0] if d else None, "last": d[-1] if d else None,
            "len_a": len(A), "len_b": len(B)}
