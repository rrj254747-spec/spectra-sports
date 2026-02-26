import os
import sqlite3
import psycopg2
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")


# =========================
# DATABASE CONNECTION
# =========================
def get_connection():
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        url = urlparse(database_url)
        return psycopg2.connect(
            dbname=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port
        )

    conn = sqlite3.connect("spectra.db")
    conn.row_factory = sqlite3.Row
    return conn


# =========================
# INIT DATABASE
# =========================
def init_db():
    conn = get_connection()
    c = conn.cursor()

    if os.environ.get("DATABASE_URL"):
        # PostgreSQL

        c.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT,
            price REAL,
            stock INTEGER
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id SERIAL PRIMARY KEY,
            total REAL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS purchase_items (
            id SERIAL PRIMARY KEY,
            purchase_id INTEGER,
            product_name TEXT,
            quantity INTEGER,
            price REAL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id SERIAL PRIMARY KEY,
            name TEXT,
            message TEXT
        )
        """)

    else:
        # SQLite

        c.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price REAL,
            stock INTEGER
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total REAL,
            date TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS purchase_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_id INTEGER,
            product_name TEXT,
            quantity INTEGER,
            price REAL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            message TEXT
        )
        """)

    conn.commit()
    conn.close()


init_db()


# =========================
# LOGIN REQUIRED
# =========================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect("/")
        return f(*args, **kwargs)
    return wrapper


# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("All fields are required", "error")
            return redirect("/")

        conn = get_connection()
        c = conn.cursor()

        if os.environ.get("DATABASE_URL"):
            c.execute("SELECT password FROM staff WHERE email=%s", (email,))
        else:
            c.execute("SELECT password FROM staff WHERE email=?", (email,))

        user = c.fetchone()
        conn.close()

        if not user:
            flash("Account does not exist", "error")
            return redirect("/")

        if not check_password_hash(user[0], password):
            flash("Incorrect password", "error")
            return redirect("/")

        session["user"] = email
        flash("Login successful", "success")
        return redirect("/dashboard")

    return render_template("login.html")


# =========================
# SIGNUP
# =========================
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("All fields are required", "error")
            return redirect("/signup")

        if len(password) < 6:
            flash("Password must be at least 6 characters", "error")
            return redirect("/signup")

        hashed = generate_password_hash(password)

        conn = get_connection()
        c = conn.cursor()

        try:
            if os.environ.get("DATABASE_URL"):
                c.execute(
                    "INSERT INTO staff (email, password, role) VALUES (%s, %s, %s)",
                    (email, hashed, "staff")
                )
            else:
                c.execute(
                    "INSERT INTO staff (email, password, role) VALUES (?, ?, ?)",
                    (email, hashed, "staff")
                )
            conn.commit()
        except:
            flash("Email already registered", "error")
            conn.close()
            return redirect("/signup")

        conn.close()
        flash("Account created successfully", "success")
        return redirect("/")

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
@login_required
def dashboard():

    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT id, name, price, stock FROM products ORDER BY name ASC")
    products = c.fetchall()

    if os.environ.get("DATABASE_URL"):
        c.execute("SELECT COALESCE(SUM(total), 0) FROM purchases")
    else:
        c.execute("SELECT IFNULL(SUM(total), 0) FROM purchases")

    total_sales = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(*) FROM staff")
    total_users = c.fetchone()[0] or 0

    conn.close()

    return render_template(
        "dashboard.html",
        products=products,
        total_sales=round(float(total_sales), 2),
        total_users=total_users
    )


# =========================
# ADD PRODUCT
# =========================
@app.route("/add_product", methods=["POST"])
@login_required
def add_product():
    name = request.form["name"]
    price = float(request.form["price"])
    stock = int(request.form["stock"])

    conn = get_connection()
    c = conn.cursor()

    if os.environ.get("DATABASE_URL"):
        c.execute(
            "INSERT INTO products (name, price, stock) VALUES (%s, %s, %s)",
            (name, price, stock)
        )
    else:
        c.execute(
            "INSERT INTO products (name, price, stock) VALUES (?, ?, ?)",
            (name, price, stock)
        )

    conn.commit()
    conn.close()

    flash("Product added successfully", "success")
    return redirect("/dashboard")


# =========================
# PURCHASE PAGE (GET)
# =========================
@app.route("/purchase", methods=["GET"])
@login_required
def purchase_page():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, price, stock FROM products")
    products = c.fetchall()
    conn.close()
    return render_template("purchase.html", products=products)


# =========================
# PURCHASE (POST)
# =========================
@app.route("/purchase", methods=["POST"])
@login_required
def purchase():

    product_ids = request.form.getlist("product_id[]")
    quantities = request.form.getlist("quantity[]")

    if not product_ids:
        flash("No items selected", "error")
        return redirect("/purchase")

    conn = get_connection()
    c = conn.cursor()

    total = 0
    selected = set()

    for i in range(len(product_ids)):

        product_id = product_ids[i]
        qty = int(quantities[i])

        if product_id in selected:
            flash("Duplicate product not allowed", "error")
            conn.close()
            return redirect("/purchase")

        selected.add(product_id)

        if os.environ.get("DATABASE_URL"):
            c.execute("SELECT name, price, stock FROM products WHERE id=%s", (product_id,))
        else:
            c.execute("SELECT name, price, stock FROM products WHERE id=?", (product_id,))

        product = c.fetchone()

        if not product:
            flash("Product not found", "error")
            conn.close()
            return redirect("/purchase")

        name, price, stock = product

        if qty > stock:
            flash(f"Not enough stock for {name}", "error")
            conn.close()
            return redirect("/purchase")

        total += float(price) * qty

        if os.environ.get("DATABASE_URL"):
            c.execute("UPDATE products SET stock = stock - %s WHERE id=%s", (qty, product_id))
        else:
            c.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, product_id))

    if os.environ.get("DATABASE_URL"):
        c.execute("INSERT INTO purchases (total) VALUES (%s)", (total,))
    else:
        c.execute("INSERT INTO purchases (total, date) VALUES (?, datetime('now'))", (total,))

    conn.commit()
    conn.close()

    flash("Purchase completed successfully", "success")
    return redirect("/dashboard")


# =========================
# FEEDBACK
# =========================
@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():

    if request.method == "POST":
        name = request.form.get("name")
        message = request.form.get("message")

        if not name or not message:
            flash("All fields are required", "error")
            return redirect("/feedback")

        conn = get_connection()
        c = conn.cursor()

        if os.environ.get("DATABASE_URL"):
            c.execute("INSERT INTO feedback (name, message) VALUES (%s, %s)", (name, message))
        else:
            c.execute("INSERT INTO feedback (name, message) VALUES (?, ?)", (name, message))

        conn.commit()
        conn.close()

        flash("Feedback submitted successfully", "success")
        return redirect("/feedback")

    return render_template("feedback.html")


if __name__ == "__main__":
    app.run(debug=True)