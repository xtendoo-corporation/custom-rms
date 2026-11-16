# -*- coding: utf-8 -*-
"""Textos ANONIMIZADOS que conservan la maquetación real (mismos saltos de
línea, columnas y orden) del texto que odoo.tools.pdf.PdfReader extrae de las
facturas de cada proveedor. Nombres, direcciones, importes, cuentas y números
de serie son inventados."""

# Meyer Sound: «Schedule B · Línea · Cantidad · Part Number · Descripción»; un
# «S/N:» por línea y los importes pegados al último S/N del artículo.
MEYER = """Invoice
Meyer Sound
Laboratories, Inc.
Telephone
(555) 010-00001000 Example Ave.
Sampletown
California 90000
Fax
(555) 010-0001Invoice Date:
Order Date:
Invoice #:
Sales Order:
Ship Via:
F.O.B.:
Ship Term:
Bill of Lading: 01/02/26
01/01/26
900001
800001
CARRIER
EX-FACTORY, SAMPLETOWN
FREIGHT COLLECT
Bill To:
9999 CLIENTE DE PRUEBA,S.L
C/EJEMPLO, 1. NAVE 2
P.I. PRUEBA
28000 MADRID
SPAIN-EORI#ESX00000000Ship To:
C/EJEMPLO, 1. NAVE 2
P.I. PRUEBA
28000 MADRID
41000 SEVILLA, SPAIN
Payment Terms:
PREPAYSales Rep#:  99
NombreCust PO:
1234
Comments: We do not find a prepay for SO 800001. Please remit your payment asap.
Schedule B Line Qty Part Number Description / Serial # Unit Price Extended
8518210000 1 3 09.338.001.04  1800-LFC,EU,OT,NO RIG,GEN-1
S/N: 26470001
S/N: 26470002
S/N: 26470003$1,000.0000 $3,000.00
8518210000 2 3 09.338.001.03  1800-LFC,EU,OT,W/RIG,GEN-1
S/N: 26470011
S/N: 26470012$2,000.0000 $6,000.00
8518908100 3 4 40.338.200.01  MCF-T2 CASTER FRAME $100.0000 $400.00
0 900 Deduction 1470
*3% PREPAY DISCOUNT*$282.00
Made in the USA unless otherwise noted.
All Prices in USD Currency.Subtotal:$9,118.00
Sales Tax: $0.00
Freight: $0.00
Total: $9,118.00
Bank Wire Information is as follows: Mail checks to:
Example Bank (Formerly Other Bank) Meyer Sound Laboratories, Inc.
1 Example Ave., Ste. 100 Attn: Accounts Receivable Dept.
Sampletown, OR 90001 1000 Example Ave.
Acct# 0000000000 Sampletown, CA 90000
ABA# 000000000
Swift Code (USD International Wire Only) XXXXUS00
"""

# Meyer Sound, repuestos: sin números de serie, todo en una línea por artículo.
MEYER_PARTS = """Invoice
Meyer Sound
Laboratories, Inc.
Schedule B Line Qty Part Number Description / Serial # Unit Price Extended
8518908100 1 1 40.205.008.02  MPS-488HP F.P. DISPLAY BOARD HTSNK II AS $111.0000 $111.00
8518908100 2 1 24.205.022.01  MPS-488HP DC FILTER PCB ASSEMBLY & BOM $22.0000 $22.00
8518908100 3 10 40.296.030.01  ST-48S DRIVER SERVICE KIT $33.0000 $330.00
8518908100 4 4 40.330.197.01  MS-2013M HF DRIVER W/HARDWARE KIT $44.0000 $176.00
0 900 Deduction 1470
3% PREPAYMENT DISCOUNT$19.17
Made in the USA unless otherwise noted.
All Prices in USD Currency.Subtotal: $619.83
Sales Tax: $0.00
Freight: $0.00
Total: $619.83
"""

# DiGiCo: cada celda de la tabla sale en su propia línea.
DIGICO = """Phone: +44 (0)1000 000000
No. 1 The Example
Sample Business Park
DiGiCo UK Ltd
Example Road
Sampleton Surrey XX0 0XX
United Kingdom
60001
EORI: GB000000000000
1 of 1
Page:
Tax ID: GB000000000
INVOICE
Seller:
Sold To:
Ship To:
1001
Linked PO:
90001
Order:
CLIENTE PRUEBA
CLIENTE PRUEBA
01/02/2026
Date:
CALLE EJEMPLO, 1
C/ PRUEBA, 2. NAVES 3- Y 4.
60 Days End of Month
Terms:
POL IND PRUEBA
EDIFICIO EJEMPLO
1234
PO Number:
SEVILLA  41000 SPAIN
MADRID.  28000
XXX
Cust. ID
SPAIN
Customer Transport
Ship Via:
Incoterms:
Ex Works Sampletown
1002
Packing Slip:
EORI:
ESX00000000
VAT ID: X00000000
Line
Part Number
Quantity
Unit Price
Ext Price
Description
1
X-A-168
2.00 EA
100.10
200.20
16 IN 8 OUT STAGE BOX
Serial Number:(s):
168-900001, 168-900002
2
X-SDR-AES-O
6.00 EA
50.50
303.00
SD RACK AES OUT XLR
HS Code:  8543909000 Country of Origin:  United Kingdom
3
X-SD-RACK-OP
1.00 EA
1,000.00
1,000.00
SD rack with HMA optics
HS Code:  8543909000 Country of Origin:  United Kingdom
Serial Number:(s):
770001-2610
1,503.20
GBP
Line(s) Subtotal:
Miscellaneous Charges:
Total
Total Tax:
0.00
0.00
1,503.20
Less Advance Billing:
0.00
Rounding:
0.00
The exporter of the products covered by this document, (Customs Authorisation no.
GB
000000000000
) declares that, except where otherwise clearly indicated, these product are of
UK preferential origin.  Place:  Sampleton  Name of Exporter:  DiGiCo UK Ltd
Tariff heading:
8543

7006

00
Please remit to: EXAMPLE Bank PLC IBAN: GB
00
XXXX
00000000000000
Swift: XXXXGB
4
B Sort code:
000000
 Account:
00000000
"""

# Luminex (factura hecha con Odoo): la referencia entre corchetes, las series
# una por línea con coma al final y la cantidad DESPUÉS, sola en su línea.
LUMINEX = """Shipping Address:
Cliente Prueba, Empresa Ejemplo S.L. Madrid
C/Ejemplo N°1 Nave 2
Parque Industrial Prueba
28000 Madrid ()
Spain
VAT:
ESX00000000
Invoice

INV/2026/09999
Invoice n°:
INV/2026/09999
Invoice Date:
01/02/2026
Due Date:
01/03/2026
Sales Order:
S09999
Your ref.:
1234 urgent 01/02
DESCRIPTION
QUANTITY
UNIT PRICE
DISC.%
VAT
AMOUNT
[LU 01 00079-POE-1G] GigaCore 10t -1G-(8 etherCON + PoE++)
Commodity Code:

85176200

Country of Origin:

Belgium
Serial Numbers:

LUM079900001,
LUM079900002,
LUM079900003,
LUM079900004,
4.00
1,000.00
 €
50.00
0%
2,000.00
 €
[LU 90 00120] Rack ear set
Commodity Code:

85176200
2.00
10.00
 €
0.00
0%
20.00
 €
Please use the following communication for your payment :
INV/2026/09999
Payment terms: 30 Days
Untaxed Amount
2,020.00 €
VAT 0%
0.00 €
Total
2,020.00 €
Luminex Lighting Control
Equipment
Examplestraat 1
0000 Sampletown
Belgium
Tel. +32 00 00 00 00 / www.example.be / VAT BE 0000.000.000
Example Bank IBAN: BE00 0000 0000 0000 / BIC (Swift): XXXXBEBB
Page:
1
 /
1
"""

# Otra factura hecha con Odoo (otro proveedor), sin números de serie: código
# arancelario antes de la cantidad y una línea de portes sin referencia.
ODOO_NO_SERIALS = """Invoice
FR/INV269999
DESCRIPTION
HS CODE
QUANTITY
UNIT PRICE
DISC.%
TAXES
AMOUNT
[AV-HY64-AVB] AVB interface for mixing systems
84718000
4.00

Unit(s)
1,000.00
 €
40.00
TVA 0%
2,400.00
 €
FEDEX Prepaid
1.00

Unit(s)
50.00
 €
0.00
TVA 0%
50.00
 €
Untaxed Amount
2,450.00 €
Total
2,450.00 €
Example Digital
Example Bank
IBAN : FR00 0000 0000 0000 0000 0000 000
"""

# DSPecialists / Harvey: posición y cantidad pegada a la marca, series
# abreviadas («-088») con los importes al final y líneas de descuento.
HARVEY = """DSPECIALISTS
Digitale Audio- und
Messsysteme GmbH
Beispielstraße 1-2 L
10000 Berlin (Beispiel)
Germany
Tel: +49-30-000 000-0
USt-IdNr:DE000000000
Example Bank AG
BLZ: 100 000 00
Kto: 000 00 00 00
IBAN:
DE00 0000 0000
0000 0000 00
BIC: XXXXDEFFXXX
DSPECIALISTS GmbH  Beispielstr. 1-2 L  10000 Berlin
Cliente Prueba, S.L.
Mr.Nombre Apellido
C/ Ejemplo, 1. Nave 2
28000 Madrid
Madrid / Spain
Customer No. VAT Number Invoice No Date
20001 ESX00000000 2609999 01.02.2026
Invoice
Your Purchase Order: PO-1234 on 01/02/2026
Dear Nombre,
in conformity with your order we invoice the following line items:
Pos. Qu.Brand / Item No / Service & Delivery Ind. Price Total Price
1 3HARVEY Pro 8x8-DA
S/N: 12-9350-019, S/N: 12-9429-087, -088 1.000,00 € 3.000,00 €
2 350% distribution discount (Pos. 1) -500,00 € -1.500,00 €
3 4HARVEY Pro 8x16
S/N: 12-9429- 069, -070, -071, -072 2.000,00 € 8.000,00 €
4 450% distribution discount (Pos. 3) -1.000,00 € -4.000,00 €
Total amount 5.500,00 €
Delivery is exempt from tax according to §4 No.1b UStG.
Delivery: Ex works / UPS 01.02.2026 (by client)
Beneficiary's A/C  No.: 000 00 00 00
IBAN No.: DE00 0000 0000 0000 0000 00
Bank Code: 100 000 00
Swift Code/BIC: XXXXDEFFXXX
"""

# Optocore: el extractor devuelve toda la factura en una sola línea.
OPTOCORE = (
    "   \nBank Account - Germany:  Example Bank München • BLZ 000 000 00 • Kto.-Nr.: 00 00 000 • Zoll-/ Customs - "
    "No.: DE0000000 Bank Account - International:  BIC/SWIFT: XXXXDEDBMUC • IBAN: DE00000000000000000000 • "
    "WEEE-Reg.-Nr.: DE 00000000 • VAT-ID: DE 000 000 000 • Amtsgericht München HRB 000.000 OPTOCORE GMBH "
    "Beispielallee 1 80000 Munich Germany Phone +49 (0) 89-000 000- 0 Fax +49 (0) 89-000 000-55 "
    "CLIENTE-PRUEBA,S.L. Calle Ejemplo 1 41000 Sevilla  Shipping address: Cliente Prueba Calle Ejemplo, 2. "
    "28000 Madrid Spain  INVOICE NO.: 26000-60000           01.02.2026 PO: 1234 Delivery time: 1 day Pos. Qty. "
    "Type Single Price Total Price 1 1 M8-OPT 4 COAXIAL MADI PORTS, 2 MADI CAT PORTS, 4 X RS485, WORD CLOCK "
    "IN/OUT, 2 OPTICAL LINKS SN: E99-0001 1.000,00 € 1.000,00 €      99  Exworks     Subtotal:  1.000,00 €   "
    "Discount:  - 500,00 €   Total:  500,00 € The following discount has been applied: 50%  Conditions: 1. The "
    "terms of payment are for a full payment before shipping.   Description of goods: Fiber Network Device\n"
)

# Waves: tabla de artículos y, más abajo, bloque «Serial Numbers».
WAVES = """1000 Example Drive
Sampleville, TN 30000
www.waves.com
Federal Tax ID 00-000000000000000Waves Inc . Invoice
No.
Date
Waves Receipt ID
Customer Ref./PO1-Feb-26
XXXXXXXXXXXX
1234
Bill To Ship To
Cliente Prueba S.L.
Calle Ejemplo 1
41000  Sevilla
Payment Terms Due Date Ship Via Tracking No .
Net 15 Days 16-Feb-26 1Z000000000000000 UPS EXPRESS SAVER
Item Code Line Total Unit Price Qty Description #
USW379-700C-334 Extreme-C SoundGrid Server 1.00 USD 1,000.00  1
Comments Sub Total USD 1,000.00
Extra Disc.  -
Freight  -
Tax  -
Invoice Total USD 1,000.00
Amount Paid  -
Balance Due USD 1,000.00Based On Sales Orders 5000000.
Serial Numbers
USW379-700C-334 Extreme-C SoundGrid Server
6C000F00A00001
By proceeding with this purchase, you acknowledge and agree to our Terms & Conditions
"""

# Documento cualquiera con rótulos de número de serie: lo único que lee el genérico.
GENERIC = """ACME Audio GmbH
Packing list 7788
Mezclador digital XR-200 (2 uds)
Nº de serie: XR200-0001; XR200-0002
Amplificador PA-900
Serial No. PA9-55A1
"""

# Facturas SIN números de serie (maquetaciones reales anonimizadas): el
# genérico no debe inventar ninguna línea.
NO_SERIALS = [
    # Tabla «unidades · precio · EAN pegado · referencia»
    """phone:+49 0000-0000000
USt.-ID:DE000000000  WEEE-Reg-Nr: DE00000000Bank: Example Bank
Account No.: 000 000 000                 00000000 00
IBAN: DE00000000000000000000     DE000000000000000000 00
BIC: XXXXDEFF400                            BIC: XXXXDEM1IBB Example Europe GmbH
Contact Person Apellido NombreInvoice No. 2026000001Date 01.02.2026
Customer ID 200000000
Unit price Total price Pos. UnitsArticle number Description
8 10,00 € 80,00 € 1612079700001 items AS-UL-B
6/8" AS Series Large Universal Surface Mount
Bracket, Black
country of origin: CN      HTS: 8518908100Net Weight: 1,73kg
Sum 80,00 €
Total 80,00 €
Invoice No. 2026000001 Page 2 of 2
""",
    # Columnas a ancho fijo con «Item:» y «Description:»
    """                                                                10001
                                                                01/02/26
                                                                REGULAR INVOICE
         Tax ID 1:  X00000000
         +34600000000                           Cliente prueba SL
     9100  1234                             0.00  UPS Standard     Net 30 Days
   3            14.000         14.000          0.000    1,000.00000        14,000.00
                 Item: 33687.006
          Description: Astral Mini Plus
                  U/M: EA
         Date Shipped: 01/02/26
                                                                           14,000.00
""",
    # «Producto EAN CantidadUnidad precio»
    """INVOICE 4900000000
Bank: Example Bank, Account No: 0000000000, IBAN: ES0000000000000000000000, SWIFT: XXXXESMX
SHIP TO600000000
600000000
600000000000000000
Product Name EAN QtyUnit Unit Price Total Net VAT Rate
Product Description
Delivery No: 5100000000 Order No: 2000000000
Purchase Order No: 1234
IERM500B.WW2 4548736175327 20PC 10,00 200,00 21,00
STEREO HEADPHONES
Total Net Value 200,00 EUR
""",
    # Una celda por línea, sin rótulos
    """Albarán AV0000001  01/02/2026
C/EJEMPLO
1
 Nº
60
 NAVE
15-16
Pedido de ventas SO000001 Referencia del cliente Nº 1234
CN-3600S E
Power Cond/Smart Seq, 240V, Smp
2,00
100,000
67,50
65,00
21
Factura
Número ......................................
26/00001
IBAN :
XXX
30000
""",
    # SKU repetido, descripción larga y «TRACKING#»
    """Page 1 of 2Example Audio Ltd
TRACKING# 1Z000000000000000
33INVOICE 10001-1
SKU TAX QTY RATEAMOUNT
2-WSC-BE 2-WSC-BE
2-Pack windscreen caps for CO-8WL lavalier microphones. Beige.No VAT 13 10.00 130.00
GO-9WD-SK-
BEGO-9WD-SK-BE
SERIES9 Omnidirectional (IP 57 waterproof) Headset Microphone with
Lemo-style connector. Color: Beige.No VAT 20 100.002,000.00
Account number: 00000000
Sort code: 00-00-00
IBAN: IE00XXXX00000000000000
""",
]
