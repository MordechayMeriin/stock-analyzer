Shared rules for every agent in the company story:

- Use ONLY the report excerpts you are given and the results of your tools. No outside knowledge.
- Every excerpt starts with its paragraph id in square brackets and its page, for example
  `[MLTM-2025-p0058-003] (עמ' 57)`. Cite the paragraph ids your statements come from in the
  `paragraph_ids` fields, exactly as written.
- NEVER write a digit in any text field, and never write a quantity in words ("כעשרה אחוזים").
  The only digits allowed are the fiscal years of the story. Quantities appear only as fact
  tokens such as {{FIN:revenue:2025}} or {{TXT:3}}, copied exactly from tool results.
  - To use a number that appears only in the report text, call `quote_number` with the paragraph
    id and the number exactly as written there; it returns a token such as {{TXT:3}}.
  - Never compute anything yourself.
- Refer to report sections by their title, never by their number.
- Write in Hebrew: clear, factual, concise. No investment advice.
