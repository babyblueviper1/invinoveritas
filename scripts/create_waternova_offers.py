#!/usr/bin/env python3
"""
Create Waternova marketplace offers — one per paid chapter + full text.
Inserts directly into the marketplace DB to avoid needing sats balance.
"""
import sqlite3
import uuid
import time
from pathlib import Path

DB_PATH = "/root/invinoveritas/data/marketplace.db"
SELLER_ID = "babyblueviper1"
LN_ADDRESS = "resourcefulspirit37499@getalby.com"
CATEGORY = "literature"

# Files 00-07 are free (served at /content/free/<filename>)
# Files 08-29 + full text are paid offers

PAID_CHAPTERS = [
    ("08-Chapter Four.docx",                        "Waternova — Chapter Four",                              1000),
    ("09-The Sky is Taking on Light.docx",           "Waternova — The Sky is Taking on Light",                1000),
    ("10-Chapter Five.docx",                         "Waternova — Chapter Five",                              1000),
    ("11-You Jump First, I_ll Watch.docx",           "Waternova — You Jump First, I'll Watch",                1000),
    ("12-Chapter Six.docx",                          "Waternova — Chapter Six",                               1000),
    ("13-Feed Me.docx",                              "Waternova — Feed Me",                                   1000),
    ("14-Chapter Seven.docx",                        "Waternova — Chapter Seven",                             1000),
    ("15-Warehouse Life Episode V_ Career Paths.docx","Waternova — Warehouse Life Episode V: Career Paths",   1000),
    ("16-Intermission II.docx",                      "Waternova — Intermission II",                           1000),
    ("17-Chapter Eight.docx",                        "Waternova — Chapter Eight",                             1000),
    ("18-Been Up So Long Looks Like Down To Me.docx","Waternova — Been Up So Long Looks Like Down To Me",     1000),
    ("19-Chapter Nine.docx",                         "Waternova — Chapter Nine",                              1000),
    ("20-Stars Are Shaking.docx",                    "Waternova — Stars Are Shaking",                         1000),
    ("21-Chapter Ten.docx",                          "Waternova — Chapter Ten",                               1000),
    ("22-Beyond the Ferris Wheel.docx",              "Waternova — Beyond the Ferris Wheel",                   1000),
    ("23-Chapter Eleven.docx",                       "Waternova — Chapter Eleven",                            1000),
    ("24-There Is a World Elsewhere.docx",           "Waternova — There Is a World Elsewhere",                1000),
    ("25-Chapter Twelve.docx",                       "Waternova — Chapter Twelve",                            1000),
    ("26-Warehouse Life Episode VI_ Contact.docx",   "Waternova — Warehouse Life Episode VI: Contact",        1000),
    ("27-Intermission III.docx",                     "Waternova — Intermission III",                          1000),
    ("28-Go Pawn It on the Mountain.docx",           "Waternova — Go Pawn It on the Mountain",                1000),
    ("29-Epilogue.docx",                             "Waternova — Epilogue",                                  1000),
    ("full text.docx",                               "Waternova — Full Novel (Federico Blanco Sánchez-Llanos)",10000),
]

CHAPTER_DESC = (
    "A chapter from Waternova, the debut novel by Federico Blanco Sánchez-Llanos. "
    "Read the prologue and first three chapters free at https://api.babyblueviper.com/content/free/. "
    "Pay 1000 sats via Lightning — download delivered instantly as .docx. "
    "© 2026 Federico Blanco Sánchez-Llanos. All rights reserved."
)

FULL_TEXT_DESC = (
    "Waternova — the complete novel by Federico Blanco Sánchez-Llanos. "
    "All 12 chapters, interludes, intermissions, prologue, and epilogue in one file. "
    "Pay 10000 sats via Lightning — download delivered instantly as .docx. "
    "© 2026 Federico Blanco Sánchez-Llanos. All rights reserved."
)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
now = int(time.time())

created = []
for filename, title, price in PAID_CHAPTERS:
    offer_id = str(uuid.uuid4())
    desc = FULL_TEXT_DESC if filename == "full text.docx" else CHAPTER_DESC
    c.execute("""
        INSERT INTO marketplace_offers
            (offer_id, seller_id, ln_address, title, description, price_sats, category, created_at, content_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (offer_id, SELLER_ID, LN_ADDRESS, title, desc, price, CATEGORY, now, filename))
    created.append((offer_id, title, price, filename))
    print(f"  ✓ [{price:,} sats] {title}")

conn.commit()
conn.close()

print(f"\n{len(created)} offers created.")
print("\nFree chapters served at:")
for f in ["00-Prologue.docx","01-Chapter One.docx","02-Opening Vibes or a Prelude to a Party.docx",
          "03-Chapter Two.docx","04-Mythmaking Monday.docx","05-Chapter Three.docx",
          "06-Warehouse Life Episode IV_ Girls.docx","07-Intermission I.docx"]:
    print(f"  https://api.babyblueviper.com/content/free/{f}")

print("\nOffer IDs (save these):")
for offer_id, title, price, _ in created:
    print(f"  {offer_id}  {title}  ({price} sats)")
