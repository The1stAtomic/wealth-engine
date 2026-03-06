from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, make_response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
import json
from datetime import datetime, timedelta
import uuid
import os
from dotenv import load_dotenv
import logging
import traceback

# --- PRODUCTION LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv()

# ANSI color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'super-secret-dev-key')

ADMIN_USERNAME = os.environ.get('APP_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('APP_PASS', 'admin123')

# Configure SQLAlchemy with SQLite database
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
os.makedirs(instance_path, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'wealth_engine.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Initialize Rate Limiter (In-Memory tracking)
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri="memory://"
)

# Define database models
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'expense' or 'income'
    
class Transaction(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    type = db.Column(db.String(10), nullable=False)  # 'expense' or 'income'
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='USD')
    category_name = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.String(20), nullable=False)
    is_investment = db.Column(db.Boolean, default=False)
    
class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    target_savings_percentage = db.Column(db.Float, default=0.0)

def check_auth(username, password):
    """Check if a username/password combination is valid."""
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        'Root Access Denied. Please provide valid credentials.', 401,
        {'WWW-Authenticate': 'Basic realm="Wealth Engine Login Required"'}
    )

# --- CUSTOM LOGIN UI & SESSION SHIELD ---

def requires_auth(f):
    """Decorator to check if user is logged into the session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# --- GLOBAL ERROR CATCHERS ---

@app.errorhandler(404)
def not_found_error(error):
    # Logs when someone (or a bot) tries to guess hidden URLs on your app
    logger.warning(f"404 WARNING: Attempted access to non-existent route -> {request.url}")
    return "Page not found.", 404

@app.errorhandler(500)
def internal_error(error):
    # 1. Protect the database from getting locked during a crash
    db.session.rollback() 
    
    # 2. Log the exact URL that caused the server to explode
    logger.critical(f"500 FATAL CRASH: Triggered by route -> {request.url}")
    
    return "Internal Server Error. The admin has been notified in the logs.", 500

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    error = None
    if request.method == 'POST':
        # Check the form inputs against our admin credentials
        if request.form['username'] != ADMIN_USERNAME or request.form['password'] != ADMIN_PASSWORD:
            error = 'ACCESS DENIED. Invalid Credentials.'
        else:
            # Success! Set the session cookie and send them to the dashboard
            session['logged_in'] = True
            logger.info("SUCCESS: Admin logged in.")
            return redirect(url_for('home'))
            
    # --- THE BFCache KILLER ---
    # Convert the template into a formal Response object so we can inject HTTP headers
    resp = make_response(render_template('login.html', error=error))
    
    # Tell the browser: "Do not save a snapshot of this secure page. Always fetch fresh."
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    
    return resp

@app.route('/logout')
def logout():
    # Destroy the session cookie
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.errorhandler(429)
def ratelimit_handler(e):
    # e.description contains the "5 per 1 minute" message
    return render_template('429.html', error=e.description), 429

# Route for the home page
@app.route('/', methods=['GET', 'POST'])
@requires_auth
def home():
  # Handle new expense submission
    # Handle new expense submission
    if request.method == 'POST':
        # 1. SANITIZE STRING INPUTS (Prevent null errors and strip whitespace)
        expense_name = request.form.get('item_name', 'Unnamed Transaction').strip()
        if not expense_name:
            expense_name = 'Unnamed Transaction'
            
        # 2. SANITIZE FLOAT INPUTS (The Crash Preventer)
        try:
            raw_cost = request.form.get('cost')
            price = float(raw_cost) if raw_cost else 0.0
        except (ValueError, TypeError):
            logger.warning(f"SECURITY/DATA WARNING: Invalid cost submitted: '{raw_cost}'. Defaulting to 0.0")
            price = 0.0

        category_choice = request.form.get('category_dropdown')
        entry_type = request.form.get('entry_type', 'expense')
        
        # 3. SANITIZE CATEGORIES
        if category_choice == "add_new":
            category = request.form.get('new_category', '').strip().title()
            if not category:
                category = "Uncategorized"
        else:
            category = category_choice if category_choice else "Uncategorized"
        
        currency = request.form.get('currency')
        is_investment = request.form.get('is_investment') == 'on'
        user_date = request.form.get('date')
        
        if user_date:
            try:
                time_part = datetime.now().strftime("%H:%M:%S")
                timestamp_str = f"{user_date} {time_part}"
            except ValueError:
                timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        if currency == "KHR":
          price /= 4000.0  # Convert KHR to USD
        
        
        # SQL category check and creation
        exiting_cat = Category.query.filter_by(name=category).first()
        if not exiting_cat:
          db.session.add(Category(name=category, type=entry_type))
        
        # Create and add the new transaction to the database
        new_tx = Transaction(
          id=str(uuid.uuid4()),
          type=entry_type,
          name = expense_name,
          amount = price,
          is_investment = is_investment,
          category_name = category,
          currency = currency,
          timestamp = timestamp_str
        )
        db.session.add(new_tx)
        
        try:
            db.session.commit()
            # Replaces the GREEN print statement
            logger.info(f"Transaction Logged: {expense_name} | {price} {currency}") 
            
        except Exception as e:
            db.session.rollback()
            # Replaces the RED print statement
            logger.error(f"DATABASE ERROR: Failed to log '{expense_name}'. Details: {str(e)}")
            
            # The Pro-Move: This logs the exact file and line number where the crash happened!
            logger.error(traceback.format_exc())
          
        return redirect('/')
      
    # ==========================================
    # --- GET REQUEST (LOADING THE DASHBOARD) ---
    # ==========================================
    
    # Load settings
    settings = Setting.query.first()
    target_savings_percentage = settings.target_savings_percentage if settings else 0.0
    
    # 1. BASE MATH (Calculated entirely by the Database)
    # db.session.query(func.sum()).scalar() returns the total or None if empty
    dynamic_income = db.session.query(func.sum(Transaction.amount)).filter_by(type='income').scalar() or 0.0
    dynamic_expenses = db.session.query(func.sum(Transaction.amount)).filter_by(type='expense').scalar() or 0.0
    
    target_savings = (target_savings_percentage / 100) * dynamic_income
    allowable_expenses = dynamic_income - target_savings - dynamic_expenses
    
    # 2. TIMEFRAME FILTERING (Sanitized with a Whitelist)
    timeframe = request.args.get('timeframe', 'all_time')
    valid_timeframes = ['all_time', 'last_24_hours', 'last_7_days', 'last_30_days', 'last_90_days']
    
    if timeframe not in valid_timeframes:
        logger.warning(f"SPOOFING ATTEMPT: Invalid timeframe '{timeframe}' requested. Resetting to all_time.")
        timeframe = 'all_time'

    now = datetime.now()
    tx_query = Transaction.query
    
    if timeframe != 'all_time':
        # (Your existing cutoff logic is fine as long as 'timeframe' is validated above)
        if timeframe == 'last_24_hours': cutoff = now - timedelta(days=1)
        elif timeframe == 'last_7_days': cutoff = now - timedelta(days=7)
        elif timeframe == 'last_30_days': cutoff = now - timedelta(days=30)
        elif timeframe == 'last_90_days': cutoff = now - timedelta(days=90)
        
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        tx_query = tx_query.filter(Transaction.timestamp >= cutoff_str)

    # 3. SORTING (Sanitized with a Whitelist)
    sort_by = request.args.get('sort', 'date_desc')
    valid_sorts = ['date_desc', 'date_asc', 'amount_desc', 'amount_asc', 'category_asc']

    if sort_by not in valid_sorts:
        logger.warning(f"SPOOFING ATTEMPT: Invalid sort '{sort_by}' requested. Resetting to date_desc.")
        sort_by = 'date_desc'
    
    if sort_by == 'date_desc': tx_query = tx_query.order_by(Transaction.timestamp.desc())
    elif sort_by == 'date_asc': tx_query = tx_query.order_by(Transaction.timestamp.asc())
    elif sort_by == 'amount_desc': tx_query = tx_query.order_by(Transaction.amount.desc())
    elif sort_by == 'amount_asc': tx_query = tx_query.order_by(Transaction.amount.asc())
    elif sort_by == 'category_asc': tx_query = tx_query.order_by(Transaction.category_name.asc())
    
    # 5. THE QUERY ENGINE: FUZZY SEARCH
    search_query = request.args.get('search', '').strip()
    if search_query:
        # .ilike() is case-insensitive. The % signs act as wildcards.
        # '%coffee%' matches "Morning Coffee", "coffee beans", and "COFFEE"
        tx_query = tx_query.filter(Transaction.name.ilike(f"%{search_query}%"))

    # 6. THE QUERY ENGINE: CATEGORY FILTER
    category_filter = request.args.get('category', 'all').strip()
    if category_filter and category_filter != 'all':
        tx_query = tx_query.filter(Transaction.category_name == category_filter)
    
    # 4. PAGINATION ENGINE
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
        
    per_page = 25  # Number of items per "chunk"
    
    # error_out=False prevents a 404 if someone types page=999999
    pagination = tx_query.paginate(page=page, per_page=per_page, error_out=False)
    transactions = pagination.items
    
    # Convert SQLAlchemy objects to dictionaries so we don't break your Jinja HTML
    display_log = [
        {
            "id": t.id, "type": t.type, "name": t.name, "amount": t.amount,
            "currency": t.currency, "category": t.category_name,
            "timestamp": t.timestamp, "is_investment": t.is_investment
        } for t in transactions
    ]

    # 4. CHART DATA (Aggregated by the Database)
    # We create a base query for expenses only, applying the same time cutoff if needed
    chart_base_query = db.session.query(Transaction).filter(Transaction.type == 'expense')
    if timeframe != 'all_time':
        chart_base_query = chart_base_query.filter(Transaction.timestamp >= cutoff_str)

    # A. Category Totals: "SELECT category_name, SUM(amount) GROUP BY category_name"
    cat_results = db.session.query(Transaction.category_name, func.sum(Transaction.amount))\
        .filter(Transaction.type == 'expense')
    if timeframe != 'all_time': cat_results = cat_results.filter(Transaction.timestamp >= cutoff_str)
    
    category_totals = {row[0]: row[1] for row in cat_results.group_by(Transaction.category_name).all()}

    # B. Investment vs Sunk Cost
    inv_results = db.session.query(Transaction.is_investment, func.sum(Transaction.amount))\
        .filter(Transaction.type == 'expense')
    if timeframe != 'all_time': inv_results = inv_results.filter(Transaction.timestamp >= cutoff_str)
    
    investment_totals = {"Investment": 0, "Sunk Cost": 0}
    for is_inv, amt in inv_results.group_by(Transaction.is_investment).all():
        if is_inv: investment_totals["Investment"] += amt
        else: investment_totals["Sunk Cost"] += amt

    # C. Trend Data: Grouping by Date Substrings
    char_length = 7 if timeframe in ['last_90_days', 'all_time'] else 10 # YYYY-MM vs YYYY-MM-DD
    
    trend_results = db.session.query(
        func.substr(Transaction.timestamp, 1, char_length).label('date_group'),
        func.sum(Transaction.amount)
    ).filter(Transaction.type == 'expense')
    
    if timeframe != 'all_time': trend_results = trend_results.filter(Transaction.timestamp >= cutoff_str)
        
    # Group by the parsed date string and order chronologically
    trend_data_query = trend_results.group_by('date_group').order_by('date_group').all()
    trend_data = {row[0]: row[1] for row in trend_data_query}

    # --- PULL CATEGORIES DIRECTLY FROM SQL TABLE! ---
    expense_categories = [c.name for c in Category.query.filter_by(type='expense').order_by(Category.name).all()]
    income_categories = [c.name for c in Category.query.filter_by(type='income').order_by(Category.name).all()]

    return render_template('index.html', budget=allowable_expenses, expenses=display_log, expense_categories=expense_categories, income_categories=income_categories, category_totals=category_totals, investment_totals=investment_totals, total_income=dynamic_income, target_savings=target_savings, target_savings_percentage=target_savings_percentage, current_sort=sort_by, current_timeframe=timeframe, trend_data=trend_data, pagination=pagination, current_category_filter=category_filter, current_search=search_query)

# Route to handle expense deletion
@app.route('/delete/<expense_id>', methods=['POST'])
@requires_auth
def delete_expense(expense_id):
  tx_to_delete = Transaction.query.get(expense_id)
  if tx_to_delete:
    db.session.delete(tx_to_delete)
    db.session.commit()
    logger.info(f"Transaction Deleted: ID {expense_id}")
  return redirect(url_for('home'))

# Route to handle expense editing (POST ONLY NOW)
@app.route('/edit/<expense_id>', methods=['POST'])
@requires_auth
def edit_expense(expense_id):
    expense_to_edit = Transaction.query.get(expense_id)
    if not expense_to_edit:
        logger.warning(f"EDIT REJECTED: Transaction ID {expense_id} not found.")
        return redirect(url_for('home'))
  
    # 1. SANITIZE NAME (Keep old name if new one is empty/whitespace)
    new_name = request.form.get('item_name', '').strip()
    if new_name:
        expense_to_edit.name = new_name
    
    # 2. SANITIZE CATEGORY
    category_choice = request.form.get('category_dropdown')
    if category_choice == "add_new":
        new_cat = request.form.get('new_category', '').strip().title()
        if new_cat:
            expense_to_edit.category_name = new_cat
            # Ensure the new category actually exists in the Category table
            if not Category.query.filter_by(name=new_cat).first():
                db.session.add(Category(name=new_cat, type=expense_to_edit.type))
    elif category_choice:
        expense_to_edit.category_name = category_choice

    # 3. SANITIZE COST (The Crash Shield)
    try:
        raw_cost = request.form.get('cost')
        if raw_cost:
            new_price = float(raw_cost)
            currency = request.form.get('currency', 'USD')
            
            # Apply your ground currency logic
            if currency == "KHR":
                new_price /= 4000.0
            
            expense_to_edit.amount = new_price
            expense_to_edit.currency = currency
    except (ValueError, TypeError):
        logger.error(f"EDIT FAILURE: Invalid cost '{raw_cost}' for ID {expense_id}. Reverting to original value.")

    # 4. SANITIZE DATE
    user_date = request.form.get('date')
    if user_date:
        try:
            # Maintain the original time of the transaction, just update the day
            old_timestamp = expense_to_edit.timestamp
            old_time = old_timestamp.split(" ")[1] if " " in old_timestamp else datetime.now().strftime("%H:%M:%S")
            expense_to_edit.timestamp = f"{user_date} {old_time}"
        except Exception:
            logger.warning(f"DATE ERROR: Could not parse date '{user_date}'. Keeping original timestamp.")

    expense_to_edit.is_investment = request.form.get('is_investment') == 'on'
    
    try:
        db.session.commit()
        logger.info(f"SUCCESS: Transaction {expense_id} updated by Admin.")
    except Exception as e:
        db.session.rollback()
        logger.critical(f"DATABASE FATAL: Update failed for {expense_id}. Error: {str(e)}")
        
    return redirect(url_for('home'))
# Route to manage categories
@app.route('/categories', methods=['GET', 'POST'])
@requires_auth
def manage_categories():
    if request.method == 'POST':
      action = request.form.get('action')
      old_category = request.form.get('old_category')
      
      if action == 'rename':
        new_category = request.form.get('new_category', '').strip().title()
        if new_category and new_category != old_category:
            # Check if the target category name already exists
            existing_cat = Category.query.filter_by(name=new_category).first()
            
            if existing_cat:
                # MERGE: Update transactions to the existing category, delete the old one
                Transaction.query.filter_by(category_name=old_category).update({"category_name": new_category})
                Category.query.filter_by(name=old_category).delete()
            else:
                # RENAME: Safe to just rename the category and transactions
                Transaction.query.filter_by(category_name=old_category).update({"category_name": new_category})
                Category.query.filter_by(name=old_category).update({"name": new_category})
                
            db.session.commit()
            logger.info(f"CAT_MGMT: Renamed '{old_category}' to '{new_category}'")
        
      return redirect(url_for('manage_categories'))
    
    categories = [c.name for c in Category.query.order_by(Category.name).all()]
    return render_template('categories.html', categories=categories)

# Route to update savings settings
@app.route('/update_savings', methods=['GET', 'POST'])
@requires_auth
def update_savings():
    settings_obj = Setting.query.first()
    if not settings_obj:
        settings_obj = Setting(target_savings_percentage=0.0)
        db.session.add(settings_obj)
  
    try:
        raw_percentage = request.form.get('target_savings_percentage')
        # We clamp it between 0 and 100 because negative savings makes no sense
        new_val = float(raw_percentage) if raw_percentage else 0.0
        settings_obj.target_savings_percentage = max(0, min(100, new_val))
        db.session.commit()
        logger.info(f"SETTINGS: Savings target updated to {settings_obj.target_savings_percentage}%")
    except (ValueError, TypeError):
        logger.warning(f"SETTINGS ERROR: Invalid percentage '{raw_percentage}' submitted.")
        db.session.rollback()

    return redirect(url_for('home'))

@app.route('/export_data', methods=['GET'])
@requires_auth
def export_data():
    transaction = Transaction.query.order_by(Transaction.timestamp.asc()).all()
    
    export_list = []
    for t in transaction:
        export_list.append({
            "id": t.id,
            "type": t.type,
            "name": t.name,
            "amount": t.amount,
            "currency": t.currency,
            "category": t.category_name,
            "timestamp": t.timestamp,
            "is_investment": t.is_investment
        })
    json_data = json.dumps(export_list, indent=4)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"wealth_engine_backup_{timestamp}.json"
    
    logger.info(f"SECURITY EVENT: Admin triggered full database export -> {filename}")
    
    return Response(
        json_data,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment;filename={filename}'}
    )

# Initialize the database and migrate existing JSON data if needed
with app.app_context():
    db.create_all()
    
    if not Setting.query.first():
      try:
        with open("settings.json", "r") as file:
          data = json.load(file)
          new_setting = Setting(target_savings_percentage=data.get("target_savings_percentage", 0))
          db.session.add(new_setting)
          db.session.commit()
          print(f"{GREEN}SUCCESS: Settings migrated to SQL!{RESET}")
      except FileNotFoundError:
          db.session.add(Setting(target_savings_percentage=0))
          db.session.commit()
          
    if not Transaction.query.first():
      try:
        with open("expense_log.json", "r") as file:
          log = json.load(file)
          for item in log:
            new_tx = Transaction(
              id=item.get("id", str(uuid.uuid4())),
              type=item.get("type", "expense"),
              name=item.get("name", "Unnamed"),
              amount=item.get("amount", 0),
              currency=item.get("currency", "USD"),
              category_name=item.get("category", "Uncategorized"),
              timestamp=item.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
              is_investment=item.get("is_investment", False)
            )
            db.session.add(new_tx)
            
            cat_name = item.get("category", "Uncategorized")
            cat_type = item.get("type", "expense")
            existing_cat = Category.query.filter_by(name=cat_name).first()
            
            if not existing_cat:
              db.session.add(Category(name=cat_name, type=cat_type))
          db.session.commit()
          print(f"{GREEN}SUCCESS: All JSON Transactions and Categories perfectly migrated to SQL!{RESET}")
      except FileNotFoundError:
          pass

if __name__ == '__main__':
    app.run(debug=True)