"""Raccolta del mese in chat (senza Telegram e senza modello) + test "di fumo" su tutti i moduli."""

import importlib
import shutil
import zipfile
from pathlib import Path

import pytest

import config
import raccolta_mese

PROVE = config.BASE / "file_di_prova" / "estere"
MODULI = sorted(p.stem for p in (config.BASE / "app").glob("*.py")
                if p.stem not in {"ottimizza_interprete", "esperimento",   # richiedono dspy/mlflow
                                  "collega_google"})                 # parte da solo: apre il browser


@pytest.mark.parametrize("modulo", MODULI)
def test_ogni_modulo_si_importa(modulo):
    # Lezione imparata: un errore di sintassi nel bot non era stato visto, perché nessun test lo importava.
    importlib.import_module(modulo)


def test_riconosce_gli_estratti_conto_dal_contenuto(tmp_path):
    amex = shutil.copy(PROVE / "estratto_amex_prova_09-2026.xlsx", tmp_path / "file qualsiasi.xlsx")
    unicredit = shutil.copy(PROVE / "estratto_unicredit_prova_09-2026.pdf", tmp_path / "documento.pdf")
    fattura = PROVE / "fatture" / "orbit-OT-8841.pdf"
    assert raccolta_mese.riconosci_estratto(Path(amex)) == "amex"
    assert raccolta_mese.riconosci_estratto(Path(unicredit)) == "unicredit"
    assert raccolta_mese.riconosci_estratto(fattura) is None


def test_raccolta_con_zip_ed_estratti(tmp_path):
    chat = "prova"
    raccolta_mese.chiudi(chat)
    cartella = raccolta_mese.apri(chat)
    assert raccolta_mese.aperta(chat) == cartella

    zip_mese = tmp_path / "settembre.zip"
    with zipfile.ZipFile(zip_mese, "w") as z:
        for f in (PROVE / "fatture").glob("*.pdf"):
            z.write(f, f"09 Settembre/{f.name}")
        z.writestr("__MACOSX/._nascosto.pdf", "spazzatura")             # da ignorare
        z.writestr("09 Settembre/note.txt", "da ignorare")
    messaggio = raccolta_mese.aggiungi(chat, zip_mese, "settembre.zip")
    assert "Dallo ZIP ho preso 7 file" in messaggio

    copia = tmp_path / "amex.xlsx"
    shutil.copy(PROVE / "estratto_amex_prova_09-2026.xlsx", copia)
    messaggio = raccolta_mese.aggiungi(chat, copia, "amex.xlsx")
    assert "7 fatture e 1 estratti conto (AMEX)" in messaggio

    copia = tmp_path / "x.docx"
    copia.write_text("no")
    assert "ignorato" in raccolta_mese.aggiungi(chat, copia, "x.docx")

    raccolta_mese.chiudi(chat)
    assert raccolta_mese.aperta(chat) is None


def test_elabora_passa_gli_estratti_giusti(monkeypatch, tmp_path):
    import elabora_mese
    chat = "prova2"
    raccolta_mese.chiudi(chat)
    cartella = raccolta_mese.apri(chat)
    shutil.copy(PROVE / "estratto_amex_prova_09-2026.xlsx", cartella / "a.xlsx")
    shutil.copy(PROVE / "estratto_unicredit_prova_09-2026.pdf", cartella / "b.pdf")
    visti = {}

    def elabora_finta(c, amex, unicredit, mese=None):
        visti.update(amex=amex.name, unicredit=unicredit.name)
        return {"fatture": [], "saltati": [], "movimenti": []}
    monkeypatch.setattr(elabora_mese, "elabora", elabora_finta)
    monkeypatch.setattr(elabora_mese, "scrivi_file", lambda r, uscita, mese: [])
    messaggio, creati = raccolta_mese.elabora(chat, "09-2026")
    assert visti == {"amex": "a.xlsx", "unicredit": "b.pdf"}
    assert "Elaborato il mese 09-2026" in messaggio and raccolta_mese.aperta(chat) is None


def test_note_brevi_per_la_registrazione():
    from elabora_mese import nota_anagrafica
    assert nota_anagrafica("Creata la scheda anagrafica di Rossi Ltd (verifica partita IVA: valida).") == \
        "nuovo fornitore: creare l'anagrafica (P.IVA valida)"
    assert nota_anagrafica('Rossi Ltd: partita IVA cambiato da "GB1" a "GB2" (fattura F1 del 2026-09-01).') == \
        'partita IVA cambiato da "GB1" a "GB2" (fattura F1 del 2026-09-01)'


def test_numero_e_data_dall_immagine_se_il_testo_non_basta(monkeypatch, tmp_path):
    """PDF con testo "incollato": numero e data mancano, si leggono dall'immagine della pagina (modello finto)."""
    import estrazione
    pdf = next(PROVE.glob("fatture/*.pdf"))
    monkeypatch.setattr(estrazione, "estrai_da_testo", lambda testo, nome, grezzo=None: {
        "_grezzo": {}, "file": nome, "numero": None, "data_emissione": None, "tipo_documento": "fattura"})
    letture = []

    def foto_finta(percorso, grezzo=None):
        letture.append(percorso.suffix)
        return {"_grezzo": {"numero": "NC-77"}, "numero": "NC-77", "data_emissione": "2026-09-12"}
    monkeypatch.setattr(estrazione, "estrai_da_foto", foto_finta)
    dati = estrazione.estrai_da_pdf(pdf)
    assert (dati["numero"], dati["data_emissione"]) == ("NC-77", "2026-09-12")
    assert dati["_grezzo_foto"] == {"numero": "NC-77"} and letture == [".png"]
    assert dati["note_lettura"][0] == "letti dall'immagine della pagina: numero, data emissione"
