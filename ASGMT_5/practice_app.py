# DAEN 328 Assignment 5, worked example dashboard (practice data, NOT graded).
# Run it from this folder with:   streamlit run practice_app.py
# It reads the practice.* tables that the Guide notebook (Part A) loads into EmployeeDB.
# New to Streamlit? Read Part C of the Guide first: C2 defines every st. function used here,
# and C3 walks through this file block by block (the numbers below match its headings).

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text

# ---------------- CONFIG: edit once ----------------
DB_NAME = "EmployeeDB"
DB_USER = "postgres"
DB_PASSWORD = "admin"      # change to YOUR PostgreSQL password
DB_HOST = "localhost"
DB_PORT = "5432"
# ----------------------------------------------------

st.set_page_config(page_title="Bean Counter Coffee", layout="wide")


# 1. ONE engine for the whole app.
#    Streamlit re-runs this whole file every time someone clicks a widget.
#    cache_resource means "build this once and reuse it on every re-run".
@st.cache_resource
def get_engine():
    return create_engine(
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


# 2. ONE helper that runs a query and returns a DataFrame.
#    cache_data remembers the result for each (sql, params) pair, so the same
#    question is not sent to Postgres again on every click. ttl=600 means the
#    cached answer expires after 10 minutes.
#    params is a dict. The SQL uses :name placeholders, and the values travel
#    separately from the SQL text, so a value with an apostrophe (O'Brien)
#    cannot break the query.
@st.cache_data(ttl=600)
def run_query(sql, params=None):
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


st.title("Bean Counter Coffee: orders dashboard")

# 3. Filters live in the sidebar. Their values feed EVERY query below.
all_stores = run_query("SELECT storename FROM practice.stores ORDER BY storename;")["storename"].tolist()
all_categories = run_query("SELECT DISTINCT category FROM practice.products ORDER BY category;")["category"].tolist()

st.sidebar.header("Filters")
chosen_stores = st.sidebar.multiselect("Stores", all_stores, default=all_stores)
chosen_category = st.sidebar.selectbox("Product category", ["All"] + all_categories)

if not chosen_stores:
    st.warning("Pick at least one store in the sidebar.")
    st.stop()

# The same two conditions are used by every query, so write them once.
#   s.storename = ANY(:stores)            -> store is in the chosen list (a Python list becomes a SQL array)
#   (:cat = 'All' OR p.category = :cat)   -> "All" switches the category filter off
FILTER_SQL = """
    FROM practice.orders o
    JOIN practice.stores   s ON o.storeid   = s.storeid
    JOIN practice.products p ON o.productid = p.productid
    WHERE s.storename = ANY(:stores)
      AND (:cat = 'All' OR p.category = :cat)
"""
params = {"stores": chosen_stores, "cat": chosen_category}

# 4. KPI row: one query, three numbers.
kpi = run_query(
    "SELECT COUNT(*) AS orders, COALESCE(SUM(o.price), 0) AS revenue, "
    "COUNT(DISTINCT o.loyaltyid) AS customers " + FILTER_SQL,
    params,
)
c1, c2, c3 = st.columns(3)
c1.metric("Orders", f"{kpi.loc[0, 'orders']:,}")
c2.metric("Revenue", f"${kpi.loc[0, 'revenue']:,.2f}")
c3.metric("Customers", f"{kpi.loc[0, 'customers']:,}")

left, right = st.columns(2)

# 5. Bar chart: let SQL do the grouping, let Plotly draw the result.
by_product = run_query(
    "SELECT p.productname, SUM(o.price) AS revenue " + FILTER_SQL +
    " GROUP BY p.productname ORDER BY revenue DESC;",
    params,
)
with left:
    st.subheader("Revenue by product")
    if by_product.empty:
        st.info("No orders match these filters.")
    else:
        fig = px.bar(by_product, x="revenue", y="productname", orientation="h",
                     labels={"revenue": "Revenue ($)", "productname": ""})
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, width="stretch")

# 6. Line chart over time: DATE_TRUNC turns each order date into the first day of its month.
by_month = run_query(
    "SELECT DATE_TRUNC('month', o.orderdate)::date AS month, s.storename, COUNT(*) AS orders " + FILTER_SQL +
    " GROUP BY month, s.storename ORDER BY month;",
    params,
)
with right:
    st.subheader("Orders per month")
    if by_month.empty:
        st.info("No orders match these filters.")
    else:
        fig = px.line(by_month, x="month", y="orders", color="storename", markers=True,
                      labels={"month": "", "orders": "Orders", "storename": "Store"})
        st.plotly_chart(fig, width="stretch")

# 7. Box plot: send the individual rows, Plotly computes the quartiles.
prices = run_query("SELECT s.storename, o.price " + FILTER_SQL + ";", params)
st.subheader("Order value by store")
if not prices.empty:
    fig = px.box(prices, x="storename", y="price", points="outliers",
                 labels={"storename": "", "price": "Order value ($)"})
    st.plotly_chart(fig, width="stretch")

# 8. Raw rows, tucked away in an expander.
with st.expander("Show matching orders"):
    detail = run_query(
        "SELECT o.ordercode, o.orderdate, s.storename, p.productname, o.price " + FILTER_SQL +
        " ORDER BY o.orderdate DESC;",
        params,
    )
    st.dataframe(detail, width="stretch", hide_index=True)
