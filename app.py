from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "spectra_secret"

# ---------- DATABASE SETUP ----------
def init_db():
    conn = sqlite3.connect("spectra.db")
    c = conn.cursor()

    # Customers table
    c.execute('''
        CREATE TABLE IF NOT EXISTS customers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            address TEXT,
            phone TEXT UNIQUE,
            dob TEXT,
            anniversary TEXT,
            interests TEXT,
            points REAL DEFAULT 0
        )
    ''')

    # Purchases table
    c.execute('''
        CREATE TABLE IF NOT EXISTS purchases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            item TEXT,
            category TEXT,
            quantity INTEGER,
            amount REAL,
            date TEXT
        )
    ''')

    # Products table
    c.execute('''
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            category TEXT,
            brand TEXT,
            price REAL,
            stock INTEGER
        )
    ''')

    # Staff table (email-based login)
    c.execute('''
        CREATE TABLE IF NOT EXISTS staff(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    ''')

    # Default owner account
    c.execute("SELECT * FROM staff WHERE email='owner@spectra.com'")
    if not c.fetchone():
        c.execute(
        "INSERT INTO staff(email, password, role) VALUES (?, ?, ?)",
        ("owner@spectra.com", generate_password_hash("1234"), "owner")
    )


    conn.commit()
    conn.close()

init_db()

# ---------- LOGIN (ENCRYPTED PASSWORD) ----------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = sqlite3.connect("spectra.db")
        c = conn.cursor()

        # Get stored password hash and role
        staff = c.execute(
            "SELECT password, role FROM staff WHERE email=?",
            (email,)
        ).fetchone()

        conn.close()

        # Check encrypted password
        if staff and check_password_hash(staff[0], password):
            session["user"] = email
            session["role"] = staff[1]
            return redirect("/dashboard")

    return render_template("login.html")

# ---------- DASHBOARD ----------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")
    return render_template("dashboard.html")

# ---------- ADD CUSTOMER ----------
@app.route("/add_customer", methods=["GET", "POST"])
def add_customer():
    if request.method == "POST":
        name = request.form["name"]
        address = request.form["address"]
        phone = request.form["phone"]
        dob = request.form["dob"]
        anniversary = request.form["anniversary"]
        interests = request.form["interests"]

        if len(phone) != 10 or not phone.isdigit():
            return "Invalid phone number"

        try:
            conn = sqlite3.connect("spectra.db")
            c = conn.cursor()
            c.execute('''
                INSERT INTO customers(name, address, phone, dob, anniversary, interests)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, address, phone, dob, anniversary, interests))
            conn.commit()
            conn.close()
        except:
            return "Phone number already exists"

        return redirect("/dashboard")

    return render_template("add_customer.html")

# ---------- CHECK EVENT WEEK ----------
def is_event_week(event_date):
    if not event_date:
        return False

    today = datetime.today()
    event = datetime.strptime(event_date, "%Y-%m-%d")

    start = event - timedelta(days=7)
    end = event

    return start.date() <= today.date() <= end.date()

# ---------- MULTI-ITEM PURCHASE (REAL POS WITH NAME) ----------
@app.route("/purchase", methods=["GET", "POST"])
def purchase():
    conn = sqlite3.connect("spectra.db")
    c = conn.cursor()

    products = c.execute("SELECT * FROM products").fetchall()

    if request.method == "POST":
        phone = request.form["phone"]

        product_ids = request.form.getlist("product")
        quantities = request.form.getlist("quantity")

        total_amount = 0
        bill_items = []

        # Get customer (with name)
        customer = c.execute(
            "SELECT name, points, dob, anniversary FROM customers WHERE phone=?",
            (phone,)
        ).fetchone()

        if not customer:
            return "Customer not found"

        name, points, dob, anniversary = customer

        # Offer message logic
        offer_message = ""
        if is_event_week(dob):
            offer_message = "🎉 Happy Birthday! Special bonus points applied."
        elif is_event_week(anniversary):
            offer_message = "🎉 Happy Anniversary! Special bonus points applied."

        for product_id, qty in zip(product_ids, quantities):
            if not product_id or not qty:
                continue

            qty = int(qty)

            if qty <= 0:
                continue

            product = c.execute(
                "SELECT name, category, price, stock FROM products WHERE id=?",
                (product_id,)
            ).fetchone()

            if not product:
                continue

            item_name, category, price, stock = product

            if qty > stock:
                return f"Not enough stock for {item_name}"

            item_total = price * qty
            total_amount += item_total

            # Reduce stock
            new_stock = stock - qty
            c.execute(
                "UPDATE products SET stock=? WHERE id=?",
                (new_stock, product_id)
            )

            # Save purchase
            c.execute('''
                INSERT INTO purchases(phone, item, category, quantity, amount, date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (phone, item_name, category, qty, item_total, datetime.today()))

            bill_items.append({
                "name": item_name,
                "category": category,
                "qty": qty,
                "total": item_total
            })

        # Points calculation
        earned_points = (total_amount / 10000) * 1.5

        if is_event_week(dob) or is_event_week(anniversary):
            earned_points *= 5

        new_points = points + earned_points

        c.execute(
            "UPDATE customers SET points=? WHERE phone=?",
            (new_points, phone)
        )

        conn.commit()
        conn.close()

        return render_template(
            "invoice.html",
            name=name,
            phone=phone,
            items=bill_items,
            total=total_amount,
            points=earned_points,
            date=datetime.now().strftime("%d-%m-%Y %H:%M"),
            offer=offer_message
        )

    conn.close()
    return render_template("purchase.html", products=products)

# ---------- REDEEM ----------
@app.route("/redeem", methods=["POST"])
def redeem():
    phone = request.form["phone"]
    redeem_points = float(request.form["points"])

    conn = sqlite3.connect("spectra.db")
    c = conn.cursor()

    customer = c.execute(
        "SELECT points FROM customers WHERE phone=?",
        (phone,)
    ).fetchone()

    if not customer:
        return "Customer not found"

    current_points = customer[0]

    if current_points < 100:
        return "Minimum 100 points required"

    if redeem_points > current_points:
        return "Not enough points"

    new_points = current_points - redeem_points

    c.execute(
        "UPDATE customers SET points=? WHERE phone=?",
        (new_points, phone)
    )
    conn.commit()
    conn.close()

    return f"Redeemed {redeem_points} points"

# ---------- SEARCH CUSTOMER ----------
@app.route("/search", methods=["GET", "POST"])
def search():
    data = None
    if request.method == "POST":
        phone = request.form["phone"]
        conn = sqlite3.connect("spectra.db")
        c = conn.cursor()
        data = c.execute(
            "SELECT * FROM customers WHERE phone=?",
            (phone,)
        ).fetchone()
        conn.close()

    return render_template("search.html", data=data)

# ---------- ADD PRODUCT ----------
@app.route("/add_product", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        name = request.form["name"]
        category = request.form["category"]
        brand = request.form["brand"]
        price = float(request.form["price"])
        stock = int(request.form["stock"])

        conn = sqlite3.connect("spectra.db")
        c = conn.cursor()
        c.execute('''
            INSERT INTO products(name, category, brand, price, stock)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, category, brand, price, stock))
        conn.commit()
        conn.close()

        return redirect("/products")

    return render_template("add_product.html")

# ---------- VIEW PRODUCTS ----------
@app.route("/products")
def products():
    conn = sqlite3.connect("spectra.db")
    c = conn.cursor()
    data = c.execute("SELECT * FROM products").fetchall()
    conn.close()
    return render_template("products.html", data=data)


# ---------- RESTOCK PRODUCT ----------
@app.route("/restock/<int:product_id>", methods=["GET", "POST"])
def restock(product_id):
    conn = sqlite3.connect("spectra.db")
    c = conn.cursor()

    product = c.execute(
        "SELECT * FROM products WHERE id=?",
        (product_id,)
    ).fetchone()

    if not product:
        conn.close()
        return "Product not found"

    if request.method == "POST":
        add_stock = int(request.form["stock"])
        new_stock = product[5] + add_stock

        c.execute(
            "UPDATE products SET stock=? WHERE id=?",
            (new_stock, product_id)
        )

        conn.commit()
        conn.close()
        return redirect("/products")

    conn.close()
    return render_template("restock.html", product=product)

# ---------- ADD STAFF ----------
@app.route("/add_staff", methods=["GET", "POST"])
def add_staff():
    if "user" not in session or session.get("role") != "owner":
        return redirect("/dashboard")

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        role = request.form["role"]

        conn = sqlite3.connect("spectra.db")
        c = conn.cursor()

        try:
            c.execute(
                "INSERT INTO staff(username, password, role) VALUES (?, ?, ?)",
                (username, password, role)
            )
            conn.commit()
        except:
            conn.close()
            return "Staff already exists"

        conn.close()
        return redirect("/dashboard")

    return render_template("add_staff.html")

# ---------- FORGOT PASSWORD ----------
@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    message = ""

    if request.method == "POST":
        email = request.form["email"]
        new_password = request.form["password"]

        conn = sqlite3.connect("spectra.db")
        c = conn.cursor()

        staff = c.execute(
            "SELECT * FROM staff WHERE email=?",
            (email,)
        ).fetchone()

        if not staff:
            conn.close()
            message = "Email not found"
            return render_template("forgot.html", message=message)

        hashed = generate_password_hash(new_password)

        c.execute(
            "UPDATE staff SET password=? WHERE email=?",
            (hashed, email)
        )

        conn.commit()
        conn.close()

        message = "Password updated successfully"

    return render_template("forgot.html", message=message)

# ---------- RUN ----------
if __name__ == "__main__":
    app.run()
