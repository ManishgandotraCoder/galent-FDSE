import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Client readout",
  description: "Assumptions, open questions for the AP head, and what is not production-ready.",
};

export default function ReadoutPage() {
  return (
    <article className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
      <header>
        <p className="text-xs font-medium tracking-[0.18em] text-accent uppercase">Northwind Fabrication</p>
        <h1 className="mt-2 font-serif text-4xl tracking-tight text-ink sm:text-5xl">Client readout</h1>
        <p className="mt-3 text-sm leading-6 text-muted">
          A one-page note on the DocProcessor prototype: what we assumed, what we would ask the AP head, and what
          is still short of a production rollout.
        </p>
      </header>

      <section className="mt-8">
        <h2 className="font-serif text-2xl text-ink">What we assumed</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-ink">
          <li>A purchase order, invoice, and goods receipt can be tied together with a PO number and an invoice number.</li>
          <li>
            Header totals may differ by up to 0.5 percent, or ₹1, whichever is larger. Unit prices must agree within
            ₹0.01. Line amounts are pre-tax, and CGST plus SGST is the tax field.
          </li>
          <li>
            The GSTIN on the document is the vendor identity. The same GSTIN with a different legal form, such as “Pvt
            Ltd” and “Private Limited”, is normalized and can clear. A different GSTIN is an exception. There is no ERP
            vendor master in this prototype.
          </li>
          <li>Currency must agree across the three documents. A disagreement is an exception even when the amounts look aligned.</li>
          <li>
            An exact duplicate is the same invoice number, vendor, amount, and purchase order. That is rejected. The
            same invoice number with a different vendor or amount is only suspicious, and the same vendor reusing a
            number on a different purchase order is a resubmission. Both wait for a person.
          </li>
          <li>
            The exception decides before the score. A soft exception is reviewed even when the read is strong. An
            unreadable file, a missing document, or an exact duplicate is rejected. With no exception, 0.95 or above
            auto-clears, 0.70 up to 0.95 is reviewed, and below 0.70 is rejected.
          </li>
          <li>
            The routing score is the weakest of completeness, extraction confidence, validation, and the match.
            Completeness is how many required fields were found. Extraction confidence is the text layer, the OCR
            score, or the model. A complete text layer is 1.00. A text layer with no issue date is 0.95. A
            photograph is capped at 0.90 and a model fill at 0.85.
          </li>
          <li>A person approves every draft. Approval is stored on the case with the rule results. This prototype has no mail gateway.</li>
          <li>
            The sample packet uses one page layout. Digital PDFs have a text layer. Three clean trios cover the
            success edges: 100% auto-clears, 95% sits on the auto-clear line, and a straight photograph is capped at
            90% and reviewed. Four other files are skewed photographs, including one mixed Hindi-English invoice. A
            generated set of variants, built by editing the clean packet, scores false auto-clears. Those variants are
            not new scans.
          </li>
        </ul>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-2xl text-ink">Questions for the AP head</h2>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-6 text-ink">
          <li>What tolerance is acceptable for quantity and price?</li>
          <li>
            Is an exact duplicate invoice number plus vendor, amount, and purchase order, and should a reused number
            with a different vendor only be reviewed?
          </li>
          <li>What happens when an invoice arrives before the goods receipt?</li>
          <li>Which exceptions can AP clear without a second person?</li>
          <li>What approval hierarchy should be used, and who may release a payment?</li>
          <li>Which ERP or accounting system should this write back to?</li>
          <li>How should credit notes and partial invoices be handled?</li>
          <li>What audit trail and retention rules apply to the draft, the decision, and the source file?</li>
        </ol>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-2xl text-ink">What is not production-ready</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-ink">
          <li>
            The layout reader fills the known page. When a required field is still missing, the whole page is sent once
            to a local Ollama model and that extraction is cached in Redis. On the labelled pack the fallback was not
            required, which is why model-token cost is zero. The model is there for the incomplete page. On the mixed
            Hindi-English photograph the numbers and the English half of each line are the reliable part. Devanagari
            still depends on OCR and the local model.
          </li>
          <li>
            Vendor resolution uses the GSTIN and the name printed on the document. It is not a vendor master from the
            ERP. A fuzzy name without a matching GSTIN is reviewed, not cleared.
          </li>
          <li>Tax and currency handling covers INR with CGST and SGST. Multi-currency, withholding, and credit notes are out of scope.</li>
          <li>There is no ERP posting, no authentication, and no role-based approval chain.</li>
          <li>
            The audit record is the case checkpoint: the rules, the four scores, the draft, and the decision. It is not
            a compliance archive.
          </li>
          <li>The 0.95 and 0.70 thresholds are starter values. They need calibration on real AP history.</li>
          <li>Email sending needs an enterprise gateway and the same human approval control.</li>
          <li>The generated variants test the rules. They do not replace a history of real vendor paper.</li>
        </ul>
      </section>
    </article>
  );
}
