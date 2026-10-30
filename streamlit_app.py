"""Synthetic-only portfolio UI; no live model or database imports."""
import streamlit as st
from text2sql.demo import demo_service, EXAMPLES, ROWS

st.set_page_config(page_title="ERP Text-to-SQL", layout="centered")
st.title("ERP Text-to-SQL")
st.caption("Bachelor project · schema retrieval and grounded T-SQL generation")
st.info("Synthetic demonstration. Questions, SQL and preview rows are fixed fixtures. "
        "No model is loaded and no database is connected.")
choice = st.selectbox("Example question", list(EXAMPLES))
question = EXAMPLES[choice]
st.write(question)
if st.button("Generate SQL", type="primary"):
    result = demo_service().run(question)
    if result.status == "SQL_VALID":
        st.success("Read-only SQL passed static schema validation.")
        st.code(result.sql, language="sql")
        st.dataframe([dict(CustomerID=r[0], Name=r[1], OrderTotal=r[2]) for r in ROWS], hide_index=True)
        st.caption("Synthetic preview fixtures; the SQL above was not executed.")
    elif result.status == "INSUFFICIENT_SCHEMA":
        st.warning("The supplied schema is insufficient for this example.")
    else:
        st.error("Request rejected by SQL validation: " + result.code)
    with st.expander("Selected schema context"):
        st.write(list(result.tables))
        for d in demo_service().retriever.documents:
            st.code(d["text"], language="text")
