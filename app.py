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

    # Production (Render PostgreSQL)
    if database_url:
        url = urlparse(database_url)
        return psycopg2.connect(
            dbname=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port
        )

    # Local (SQLite)
    else:
        conn = sqlite3.connect("spectra.db")
        conn.row_factory = sqlite3.Row
        return conn


# =========================
# INIT DATABASE
# =========================
def init_db():
    conn = get_connection()
    c = conn.cursor()

    # STAFF / USERS
    c.execute("""
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        password TEXT,
        role TEXT
    )
    """)

    # PRODUCTS
    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price REAL,
        stock INTEGER
    )
    """)

    # PURCHASES
    c.execute("""
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        total REAL,
        date TEXT
    )
    """)

    # PURCHASE ITEMS
    c.execute("""
    CREATE TABLE IF NOT EXISTS purchase_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER,
        product_name TEXT,
        quantity INTEGER,
        price REAL
    )
    """)

    # FEEDBACK
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
# LOGIN REQUIRED DECORATOR
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

        # Backend validation
        if not email or not password:
            flash("All fields are required", "error")
            return redirect("/")

        if "@" not in email:
            flash("Invalid email format", "error")
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

        # Backend validation
        if not email or not password:
            flash("All fields are required", "error")
            return redirect("/signup")

        if "@" not in email or "." not in email:
            flash("Invalid email format", "error")
            return redirect("/signup")

        if len(password) < 6:
            flash("Password must be at least 6 characters", "error")
            return redirect("/signup")

        if not any(char.isdigit() for char in password):
            flash("Password must contain at least one number", "error")
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


# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# DASHBOARD (Keep Old Design)
# =========================
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_connection()
    c = conn.cursor()

    if os.environ.get("DATABASE_URL"):
        c.execute("SELECT id, name, price, stock FROM products")
    else:
        c.execute("SELECT id, name, price, stock FROM products")

    products = c.fetchall()
    conn.close()

    return render_template("dashboard.html", products=products)


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

    flash("Product added successfully")
    return redirect("/dashboard")


# =========================
# PURCHASE (Dynamic Infinite Billing + No Duplicate + Price Support)
# =========================
@app.route("/purchase", methods=["POST"])
@login_required
def purchase():

    products = request.form.getlist("product[]")
    prices = request.form.getlist("price[]")
    qtys = request.form.getlist("qty[]")
    grand_total = request.form.get("grand_total")

    selected = set()
    total = 0

    conn = get_connection()
    c = conn.cursor()

    for i in range(len(products)):

        name = products[i]
        qty = int(qtys[i])
        price = float(prices[i])

        # Prevent duplicate product in same bill
        if name in selected:
            flash("Duplicate product in bill")
            conn.close()
            return redirect("/dashboard")

        selected.add(name)

        # Check stock from database
        if os.environ.get("DATABASE_URL"):
            c.execute("SELECT stock FROM products WHERE name=%s", (name,))
        else:
            c.execute("SELECT stock FROM products WHERE name=?", (name,))

        product = c.fetchone()

        if not product:
            flash(f"Product {name} not found")
            conn.close()
            return redirect("/dashboard")

        stock = product[0]

        if qty > stock:
            flash(f"Not enough stock for {name}")
            conn.close()
            return redirect("/dashboard")

        # Calculate row total
        row_total = price * qty
        total += row_total

        # Reduce stock
        if os.environ.get("DATABASE_URL"):
            c.execute(
                "UPDATE products SET stock = stock - %s WHERE name=%s",
                (qty, name)
            )
        else:
            c.execute(
                "UPDATE products SET stock = stock - ? WHERE name=?",
                (qty, name)
            )

    # Insert purchase summary
    if os.environ.get("DATABASE_URL"):
        c.execute(
            "INSERT INTO purchases (total, date) VALUES (%s, NOW())",
            (total,)
        )
    else:
        c.execute(
            "INSERT INTO purchases (total, date) VALUES (?, datetime('now'))",
            (total,)
        )

    conn.commit()
    conn.close()

    flash("Purchase completed successfully")
    return redirect("/dashboard")

# =========================
# FEEDBACK
# =========================
@app.route("/feedback", methods=["POST"])
@login_required
def feedback():
    name = request.form["name"]
    message = request.form["message"]

    conn = get_connection()
    c = conn.cursor()

    if os.environ.get("DATABASE_URL"):
        c.execute(
            "INSERT INTO feedback (name, message) VALUES (%s, %s)",
            (name, message)
        )
    else:
        c.execute(
            "INSERT INTO feedback (name, message) VALUES (?, ?)",
            (name, message)
        )

    conn.commit()
    conn.close()

    flash("Feedback submitted")
    return redirect("/dashboard")


if __name__ == "__main__":
    app.run(debug=True)