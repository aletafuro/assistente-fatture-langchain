"""
Genera le FATTURE ESTERE DI PROVA e gli ESTRATTI CONTO finti (dati inventati).

Ogni fattura riproduce un caso incontrato su fatture vere, con nomi e numeri di fantasia:
partita IVA nel piè di pagina, data americana, trattino nel numero (stile Stripe), valuta scritta "CSK",
nome diverso sull'estratto conto, importo dovuto diverso dal totale, fornitore senza partita IVA.

Uso (dalla cartella v3):  uv run python file_di_prova/estere/genera_prove_estere.py
Richiede Microsoft Edge (stampa HTML -> PDF, come per le altre fatture di prova).
"""

import subprocess
import tempfile
import time
from pathlib import Path

from openpyxl import Workbook

QUI = Path(__file__).resolve().parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CLIENTE = "Impresa Cliente SRL<br>Corso Italia 1<br>70121 Bari (BA)<br>Italy"
STILE = """<style>body{font-family:Arial,sans-serif;font-size:12px;margin:28px;color:#222}
h1{font-size:22px;margin:0 0 12px} table{border-collapse:collapse;width:100%;margin:14px 0}
td,th{border-bottom:1px solid #ccc;padding:6px;text-align:left} .r{text-align:right}
.piede{position:fixed;bottom:20px;left:28px;right:28px;font-size:10px;color:#555;border-top:1px solid #ccc;padding-top:6px}
.colonne{display:flex;justify-content:space-between}</style>"""

FATTURE = {
    "northwind-INV000777.pdf": f"""<div class="colonne"><div><b>Northwind Analytics Inc.</b><br>5670 Sunset Blvd, Suite 900<br>
Los Angeles CA 90036<br>United States</div><div><h1>Invoice</h1>Invoice INV000777<br>Date 9/17/2026<br>Payment Terms Net 7</div></div>
<p><b>Bill To:</b><br>{CLIENTE}</p>
<table><tr><th>Description</th><th>Qty</th><th class="r">Unit Price</th><th class="r">Ext. Price</th></tr>
<tr><td>Dispute resolution service</td><td>89</td><td class="r">$15.00</td><td class="r">$1,335.00</td></tr></table>
<p>Subtotal $1,335.00<br>Tax $0.00<br><b>Current Charge $1,335.00</b></p>
<p>Remittance: wire transfer to Northwind Analytics Inc., Bank of Example, SWIFT EXAMUS00</p>""",

    "balticpixel-BP-2026-0042.pdf": f"""<h1>Invoice</h1>Invoice number BP-2026-0042<br>Date of issue September 17, 2026<br>
Date due September 18, 2026
<p><b>Baltic Pixel UAB</b><br>Gedimino g. 10<br>LT-44319 Kaunas<br>Lithuania</p>
<p><b>Bill to</b><br>{CLIENTE}<br>IT VAT IT09999999999</p>
<table><tr><th>Description</th><th>Qty</th><th class="r">Unit price</th><th>Tax</th><th class="r">Amount</th></tr>
<tr><td>Creative pack: 20 short videos</td><td>1</td><td class="r">$1,000.00</td><td>0%</td><td class="r">$1,000.00</td></tr></table>
<p>Subtotal $1,000.00<br><b>Total $1,000.00</b><br>Amount due $1,000.00 USD</p>
<p>Tax to be paid on reverse charge basis</p>
<div class="piede">Baltic Pixel UAB · Company code 300000001 · LT VAT LT100000000011 · IBAN LT00 0000 0000 0000 0000</div>""",

    "cloudnest-A1B2C3D4-0007.pdf": f"""<div class="colonne"><div><h1>Invoice</h1>Invoice number A1B2C3D4-0007<br>Date of issue September 21, 2026<br>
Date due September 21, 2026</div><div><b>CloudNest LLC</b><br>900 Villa Street<br>Mountain View, California 94041<br>United States<br>
EU OSS VAT EU372000041</div></div>
<p><b>Bill to</b><br>{CLIENTE}<br>IT VAT IT09999999999</p>
<table><tr><th>Description</th><th>Qty</th><th class="r">Unit price</th><th>Tax</th><th class="r">Amount</th></tr>
<tr><td>Nestbox Pro (Sep 21 - Oct 21, 2026)</td><td>1</td><td class="r">99.00 USD</td><td>0%</td><td class="r">99.00 USD</td></tr></table>
<p>Subtotal 99.00 USD<br><b>Total 99.00 USD</b><br>Amount paid 99.00 USD</p>
<p>Payment method: American Express •••• 1009</p>""",

    "brightline-BL-5531.pdf": f"""<h1>INVOICE BL-5531</h1>Issued: 12 Sep 2026
<div class="colonne"><div><b>From</b><br>Brightline Ltd<br>27 Giles Street<br>Norwich NR2 1JN<br>United Kingdom<br>VAT: GB123456789</div>
<div><b>To</b><br>{CLIENTE}</div></div>
<table><tr><th>Description</th><th class="r">Price (excl. VAT)</th><th>VAT rate</th><th class="r">Total</th></tr>
<tr><td>GDPR compliance review</td><td class="r">£149.00</td><td>0%</td><td class="r">£149.00</td></tr></table>
<p><b>Amount due £149.00</b> — please pay by bank transfer within 30 days.</p>""",

    "lumen-NL2026090001.pdf": f"""<div class="colonne"><div><b>Impresa Cliente SRL</b> &nbsp; Invoice Number : NL2026090001<br>
Corso Italia 1 &nbsp; Company Code : IMPRESACL<br>70121 Bari &nbsp; Description : Software licences<br>ITALY &nbsp; Period : August 2026</div>
<div><h1>INVOICE</h1>Lumen Software B.V.<br>Herengracht 100<br>1015 BS AMSTERDAM<br>THE NETHERLANDS<br>Invoice Date : 1 September 2026</div></div>
<table><tr><td>Licences</td><td class="r">EUR 1,350.00</td></tr><tr><td>Support</td><td class="r">EUR 131.35</td></tr>
<tr><td>Invoice Total excluding taxes</td><td class="r">EUR 1,481.35</td></tr><tr><td>VAT 0.0%</td><td class="r">EUR 0.00</td></tr>
<tr><td><b>Invoice Total including taxes</b></td><td class="r"><b>EUR 1,481.35</b></td></tr>
<tr><td>Already deducted from settlement</td><td class="r">EUR 932.53</td></tr><tr><td>Amount due</td><td class="r">EUR 548.82</td></tr></table>
<p>Services reverse charge based on art. 196 EU VAT Directive</p>
<div class="piede">Lumen Software B.V. · Chamber of Commerce 30000001 · VAT REG: NL.800000001.B.01</div>""",

    "orbit-OT-8841.pdf": f"""<h1>Receipt</h1>Receipt number OT-8841<br>Date paid Sep 11, 2026
<p><b>Orbit Tools Inc.</b><br>350 Fifth Avenue<br>New York, NY 10118<br>United States</p>
<p><b>Billed to</b><br>{CLIENTE}</p>
<table><tr><th>Description</th><th class="r">Amount</th></tr><tr><td>Team plan, 2 seats (monthly)</td><td class="r">$18.10</td></tr></table>
<p><b>Total $18.10</b><br>Payment method: Mastercard ending 3978</p>""",

    "skyhop-SKY413572535.pdf": f"""<h1>FATTURA / INVOICE SKY413572535</h1>Data / Date: 10/09/2026
<div class="colonne"><div><b>Skyhop a.s.</b><br>K Letišti 6<br>160 08 Praha 6<br>Czech Republic<br>DIČ: CZ12345678</div>
<div><b>Cliente / Customer</b><br>{CLIENTE}</div></div>
<table><tr><th>Descrizione</th><th class="r">Importo</th></tr><tr><td>Volo Praga - Milano, 3 passeggeri, bagagli</td><td class="r">46.887,00</td></tr></table>
<p><b>CZ &nbsp; TOTALE FATTURA (CSK) 46.887,00</b><br>TOTALE PAGAMENTO 46.887,00</p>""",
}

UNICREDIT = """<h2>ESTRATTO CONTO CARTA DI CREDITO AL 30.09.2026</h2><p>Banca Esempio - Espresso in: EUR</p>
<p>Data Registrazione Riferimento Operazione Descrizione Importo in divisa estera Divisa Cambio Importo in Euro</p>
<p>14.09.26 H07371 Pagamento E-Commerce ORBIT TOOLS NEW YORK 11.09.26 18,10 USD 1,15877 15,62</p>
<p>14.09.26 H07371 Commissione per cambio divisa estera ORBIT TOOLS NEW YORK 11.09.26 0,27</p>
<p>16.09.26 H74788 Pagamento E-Commerce MUSICA STREAM LEEDS 14.09.26 6,99</p>
<p>Totale 22,88</p>"""

AMEX = [
    # data, descrizione, importo addebitato (EUR), dettagli completi, paese
    ("09/30/2026", "BALTICPIXEL   KAUNAS", 887.41,
     "Foreign Spend Amount: 1,000.00 Dollari Statunitensi Commission Amount: 19.81 Currency Exchange Rate: 1.1526", "LITHUANIA"),
    ("09/21/2026", "NESTBOX   MOUNTAIN VIEW", 88.32,
     "Foreign Spend Amount: 99.00 Dollari Statunitensi Commission Amount: 1.93 Currency Exchange Rate: 1.1459", "UNITED STATES"),
    ("09/09/2026", "SKYHOP   PRAHA", 1988.76,
     "Foreign Spend Amount: 46,887.00 Corone Cecoslovacche Commission Amount: 48.51 Currency Exchange Rate: 24.1654",
     "CZECH REPUBLIC"),
    ("09/12/2026", "CAFFETTERIA CENTRALE   MILANO", 12.50, "", "ITALY"),
]


def stampa_pdf(html: str, pdf: Path) -> None:
    tmp = Path(tempfile.mkdtemp()) / "pagina.html"
    tmp.write_text(f"<!doctype html><html><head><meta charset='utf-8'>{STILE}</head><body>{html}</body></html>",
                   encoding="utf-8")
    pdf.unlink(missing_ok=True)
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.gettempdir()}\\edge-pdf-profile", f"--print-to-pdf={pdf}",
                    tmp.as_uri()], capture_output=True)
    for _ in range(30):
        if pdf.exists() and pdf.stat().st_size > 1000:
            return
        time.sleep(1)
    raise RuntimeError(f"PDF non creato: {pdf}")


def main():
    (QUI / "fatture").mkdir(exist_ok=True)
    for nome, html in FATTURE.items():
        stampa_pdf(html, QUI / "fatture" / nome)
        print("creata", nome)
    stampa_pdf(UNICREDIT, QUI / "estratto_unicredit_prova_09-2026.pdf")
    wb = Workbook()
    ws = wb.active
    ws.title = "Dettagli transazione"
    ws.append(["Dettagli transazione", "Carta Business di prova / 01 Sep, 2026 a 30 Sep, 2026"])
    ws.append(["Per", "MARIO ROSSI"])
    ws.append([])
    ws.append(["Data", "Descrizione", "Titolare", "Numero di Carta", "Importo", "Dettagli completi",
               "Compare sul tuo estratto conto come", "Paese", "Riferimento"])
    for i, (data, descr, importo, dettagli, paese) in enumerate(AMEX, start=1):
        ws.append([data, descr, "MARIO ROSSI", "-11009", importo, dettagli, descr, paese, f"AT00000000{i}"])
    wb.save(QUI / "estratto_amex_prova_09-2026.xlsx")
    print("creati gli estratti conto di prova")


if __name__ == "__main__":
    main()
