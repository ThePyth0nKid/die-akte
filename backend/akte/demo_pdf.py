"""Kleinster PDF-Erzeuger für die erfundenen Quellen der Demo-Akte (Text, Helvetica, WinAnsi).

Kein Fremdpaket, keine Metadaten (kein Autor, kein Pfad, kein Datum), daher byte-gleich bei gleichem Text.
Jede Seite ist eine Liste von Zeilen; pdfium liest den Text wieder heraus, also funktionieren Fundstellen.
"""

from __future__ import annotations


def _pdf_text(zeile: str) -> bytes:
    roh = zeile.encode("cp1252", errors="replace")
    return roh.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pdf(seiten: list[list[str]], titel: str = "") -> bytes:
    objekte: list[bytes] = []

    def neu(inhalt: bytes) -> int:
        objekte.append(inhalt)
        return len(objekte)

    katalog = neu(b"")  # wird unten gefüllt
    seiten_obj = neu(b"")
    schrift = neu(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    kinder = []
    for zeilen in seiten:
        teile = [b"BT /F1 11 Tf 14 TL 56 780 Td"]
        if titel:
            teile.append(b"/F1 15 Tf (" + _pdf_text(titel) + b") Tj T* T* /F1 11 Tf")
        for z in zeilen:
            teile.append(b"(" + _pdf_text(z) + b") Tj T*")
        teile.append(b"ET")
        strom = b"\n".join(teile)
        inhalt = neu(b"<< /Length " + str(len(strom)).encode() + b" >>\nstream\n" + strom + b"\nendstream")
        kinder.append(neu(f"<< /Type /Page /Parent {seiten_obj} 0 R /MediaBox [0 0 595 842] "
                          f"/Resources << /Font << /F1 {schrift} 0 R >> >> /Contents {inhalt} 0 R >>".encode()))
    objekte[katalog - 1] = f"<< /Type /Catalog /Pages {seiten_obj} 0 R >>".encode()
    objekte[seiten_obj - 1] = (f"<< /Type /Pages /Count {len(kinder)} /Kids ["
                               + " ".join(f"{k} 0 R" for k in kinder) + "] >>").encode()

    aus = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    versatz = []
    for nr, inhalt in enumerate(objekte, start=1):
        versatz.append(len(aus))
        aus += f"{nr} 0 obj\n".encode() + inhalt + b"\nendobj\n"
    xref = len(aus)
    aus += f"xref\n0 {len(objekte) + 1}\n0000000000 65535 f \n".encode()
    for v in versatz:
        aus += f"{v:010d} 00000 n \n".encode()
    aus += f"trailer\n<< /Size {len(objekte) + 1} /Root {katalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(aus)
