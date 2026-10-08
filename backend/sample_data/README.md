# Sample documents

29 synthetic accounts-payable documents for Northwind Fabrication Pvt Ltd, Pune.
Amounts are INR. GST is split into CGST and SGST on the page and stored as one `tax` field.

Digital PDFs have a text layer. A complete text layer scores 100%. A text layer with no issue date scores 95%, which is the auto-clear line. A photograph is capped at 90%, so a clean photo match is reviewed.

The skewed `.jpg` files need OCR or a vision model. `20-inv-5520-gupta-hindi.jpg` is mixed Hindi and English. `27` through `29` are straight photographs of a clean trio.

Upload each success trio on its own. Matching the whole pack in one case mixes the planted errors into the clean sets. The workbench holds 20 files at a time. A case is three documents, or four when the duplicate invoice is included.

## Cases

- **apex-steel-clean** (matched: none). PO, invoice, and goods receipt agree on vendor, price, and quantity. Files: `01-po-24018-apex-steel.pdf`, `02-inv-77821-apex-steel.pdf`, `03-grn-31018-apex-steel.pdf`.
- **bharat-partial-delivery** (exception: quantity_mismatch, partial_delivery). Ordered 100 bearings, warehouse received 60, invoice bills 100. Files: `04-po-24019-bharat-bearings.pdf`, `05-inv-88044-bharat-bearings.pdf`, `06-grn-31019-bharat-bearings.pdf`.
- **lakshmi-wrong-total** (exception: total_mismatch). Invoice lines plus GST equal Rs. 9,735.00. The printed total is Rs. 9,375.00. Files: `07-po-24020-lakshmi-fasteners.pdf`, `08-inv-99107-lakshmi-fasteners.pdf`, `09-grn-31020-lakshmi-fasteners.pdf`.
- **acme-legal-name** (matched: none). PO and GRN say "Acme Pvt Ltd". The invoice says "ACME Private Limited". The GSTIN matches, so the legal-form difference is normalized. Files: `10-po-24021-acme-pvt.pdf`, `11-inv-77890-acme-private.pdf`, `12-grn-31021-acme-pvt.pdf`.
- **western-different-vendor** (exception: vendor_mismatch). Goods were ordered from Western Hydraulics Ltd and received from them. The bill is from Deccan Hydraulics. Files: `13-po-24022-western-hydraulics.pdf`, `14-inv-44210-deccan-hydraulics.pdf`, `15-grn-31022-western-hydraulics.pdf`.
- **apex-duplicate-invoice** (exception: duplicate_invoice). INV-77821 is submitted twice. The purchase order, the first invoice, and the goods receipt still agree. Files: `01-po-24018-apex-steel.pdf`, `02-inv-77821-apex-steel.pdf`, `03-grn-31018-apex-steel.pdf`, `16-inv-77821-apex-resubmit.pdf`.
- **gupta-hindi-unpaired** (incomplete: missing_document). Mixed Hindi-English invoice with no purchase order or goods receipt in the pack. Files: `20-inv-5520-gupta-hindi.jpg`.
- **success-100-orion** (matched: none). Digital purchase order, invoice, and goods receipt agree, and every field including the issue date is printed. Upload these three files together. The read is 100% and the case auto-clears. Files: `21-po-24040-orion-castings.pdf`, `22-inv-10040-orion-castings.pdf`, `23-grn-31040-orion-castings.pdf`.
- **success-95-shakti** (matched: none). Digital trio that agrees on vendor, price, and quantity. The issue date is not printed, so extraction confidence sits on the 95% auto-clear line. Upload these three files together. Files: `24-po-24041-shakti-gaskets.pdf`, `25-inv-10041-shakti-gaskets.pdf`, `26-grn-31041-shakti-gaskets.pdf`.
- **success-90-metro** (matched: none). Straight photographs of a clean trio. The documents agree. A photograph is capped at 90%, under the 95% auto-clear line, so the case is reviewed. Upload these three files together. Files: `27-po-24042-metro-polymers.jpg`, `28-inv-10042-metro-polymers.jpg`, `29-grn-31042-metro-polymers.jpg`.

Three photographs are skewed copies of the Bharat invoice, the Bharat goods receipt, and the Lakshmi purchase order. Their labels point at those PDFs. The fourth photograph is the Hindi invoice. Three more are straight photographs of the Metro Polymers trio, kept so a clean photo can be tested at the 90% cap.

Regenerate with:

```bash
cd backend
uv run python scripts/generate_sample_data.py
```
