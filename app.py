from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, make_response, flash, send_file, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from dateutil.relativedelta import relativedelta
import bcrypt
import hmac
import json
from datetime import datetime, timedelta
import uuid
import os
from dotenv import load_dotenv
import logging

load_dotenv()

# --- PRODUCTION LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- NAMED CONSTANTS ---
KHR_TO_USD_RATE = Decimal('4000')
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"
DEFAULT_CATEGORY = "Uncategorized"
ADD_NEW_SENTINEL = "add_new"
VALID_ENTRY_TYPES = {'expense', 'income'}
VALID_CURRENCIES = {'USD', 'KHR'}
VALID_FREQUENCIES = {'daily', 'weekly', 'monthly'}

# Receipt image storage
MAX_RECEIPT_BYTES = 5 * 1024 * 1024  # 5 MB hard cap
# Magic-byte signatures mapped to file extension: (byte_offset, signature_bytes)
ALLOWED_IMAGE_MAGIC: dict[str, tuple[int, bytes]] = {
    'jpg':  (0, b'\xff\xd8\xff'),
    'png':  (0, b'\x89PNG'),
    'webp': (8, b'WEBP'),
    'gif':  (0, b'GIF8'),
}

# KISS: dict replaces 4-branch if/elif chain for timeframe → cutoff delta
TIMEFRAME_DELTAS = {
    'last_24_hours': timedelta(days=1),
    'last_7_days':   timedelta(days=7),
    'last_30_days':  timedelta(days=30),
    'last_90_days':  timedelta(days=90),
}

# char_length for func.substr on timestamp string determines trend grouping granularity
TIMEFRAME_CHAR_LENGTHS = {
    'last_24_hours': 13,  # group by hour:  "YYYY-MM-DD HH"
    'last_7_days':   10,  # group by day:   "YYYY-MM-DD"
    'last_30_days':  10,  # group by day:   "YYYY-MM-DD"
    'last_90_days':   7,  # group by month: "YYYY-MM"
    'all_time':       7,  # group by month: "YYYY-MM"
}

app = Flask(__name__)

@app.template_filter('fmt_money')
def fmt_money(value):
    """Format a number as $1,234.56 with correct sign placement for negatives."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '$0.00'
    if v < 0:
        return f'-${abs(v):,.2f}'
    return f'${v:,.2f}'

@app.template_filter('fmt_short_date')
def fmt_short_date(value):
    """Convert 'YYYY-MM-DD HH:MM:SS' string to 'DD MMM' (e.g., '09 MAR')."""
    try:
        # Parse the string into a real Python datetime object
        dt = datetime.strptime(value, TIMESTAMP_FORMAT)
        # Format it and uppercase it for the terminal aesthetic
        return dt.strftime('%d %b').upper()
    except (ValueError, TypeError):
        # Fallback safeguard: if parsing fails, just slice the YYYY-MM-DD part
        return str(value)[:10]

# --- STARTUP CREDENTIAL GUARD ---
# If any of these env vars are missing, crash immediately rather than run with weak defaults.
_secret_key = os.environ.get('FLASK_SECRET_KEY')
_admin_user = os.environ.get('APP_USER')
_admin_pass = os.environ.get('APP_PASS')

if not _secret_key or not _admin_user or not _admin_pass:
    raise RuntimeError(
        "STARTUP FAILED: FLASK_SECRET_KEY, APP_USER, and APP_PASS must all be set in your .env file. "
        "The app will not start with missing credentials."
    )
# FIX: catch weak keys early — a 4-character secret key would pass the non-empty check above
if len(_secret_key) < 32:
    raise RuntimeError(
        "STARTUP FAILED: FLASK_SECRET_KEY must be at least 32 characters. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

app.secret_key = _secret_key

# FIX: harden session cookie
# Set SESSION_COOKIE_SECURE=false in .env only when running locally over plain HTTP.
app.config['SESSION_COOKIE_SECURE']   = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# FIX: sessions now expire after 8 hours of inactivity instead of living forever
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

csrf = CSRFProtect(app)

ADMIN_USERNAME = _admin_user
# Hash the plaintext password once at startup. bcrypt.checkpw() is used at login time.
ADMIN_PASSWORD_HASH = bcrypt.hashpw(_admin_pass.encode('utf-8'), bcrypt.gensalt())

# Configure SQLAlchemy with SQLite database
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
os.makedirs(instance_path, exist_ok=True)
RECEIPTS_DIR = os.path.join(instance_path, 'receipts')
os.makedirs(RECEIPTS_DIR, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'wealth_engine.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Default is in-memory (resets on restart — rate limit counters lost on crash/deploy).
# Set RATELIMIT_STORAGE_URI=redis://localhost:6379 in .env for persistent limits.
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
)

# Define database models
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'expense' or 'income'
    monthly_budget = db.Column(db.Numeric(18, 2), nullable=True)  # NULL = no budget set

class Transaction(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    type = db.Column(db.String(10), nullable=False)  # 'expense' or 'income'
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(precision=18, scale=2), nullable=False)  # FIX: was Float; Decimal avoids rounding errors
    currency = db.Column(db.String(3), nullable=False, default='USD')
    category_name = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.String(20), nullable=False)  # 'YYYY-MM-DD HH:MM:SS' — lexicographic order == chronological order
    is_investment = db.Column(db.Boolean, default=False)
    note = db.Column(db.Text, nullable=True)
    receipt_filename = db.Column(db.String(255), nullable=True)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    target_savings_percentage = db.Column(db.Numeric(5, 2), default=0.0)
    trash_expiry_days = db.Column(db.Integer, default=30)

class RecurringTransaction(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    amount        = db.Column(db.Numeric(18, 2), nullable=False)  # stored in USD
    currency      = db.Column(db.String(3), nullable=False, default='USD')
    type          = db.Column(db.String(10), nullable=False)  # 'expense' or 'income'
    category_name = db.Column(db.String(50), nullable=False)
    is_investment = db.Column(db.Boolean, default=False)
    frequency     = db.Column(db.String(10), nullable=False)  # 'daily', 'weekly', 'monthly'
    next_due      = db.Column(db.String(10), nullable=False)  # 'YYYY-MM-DD'

class DeletedTransaction(db.Model):
    """Archive of soft-deleted transactions. Restored rows move back to Transaction."""
    __tablename__ = 'deleted_transaction'
    id               = db.Column(db.String(36), primary_key=True)
    type             = db.Column(db.String(10), nullable=False)
    name             = db.Column(db.String(100), nullable=False)
    amount           = db.Column(db.Numeric(precision=18, scale=2), nullable=False)
    currency         = db.Column(db.String(3), nullable=False, default='USD')
    category_name    = db.Column(db.String(50), nullable=False)
    timestamp        = db.Column(db.String(20), nullable=False)  # 'YYYY-MM-DD HH:MM:SS'
    is_investment    = db.Column(db.Boolean, default=False)
    note             = db.Column(db.Text, nullable=True)
    receipt_filename = db.Column(db.String(255), nullable=True)
    deleted_at       = db.Column(db.String(20), nullable=False)  # 'YYYY-MM-DD HH:MM:SS' — lexicographic order == chronological order


class NetWorthItem(db.Model):
    """A manually-maintained asset or liability balance used for net worth tracking."""
    __tablename__ = 'net_worth_item'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    item_type    = db.Column(db.String(10), nullable=False)   # 'asset' | 'liability'
    category     = db.Column(db.String(20), nullable=False)   # 'bank'|'investment'|'property'|'loan'|'credit'|'other'
    balance      = db.Column(db.Numeric(18, 2), nullable=False)
    last_updated = db.Column(db.String(10), nullable=False)   # YYYY-MM-DD

# KISS: dict replaces 5-branch if/elif chain for sort key → order expression.
# Defined after Transaction so SQLAlchemy column descriptors are available.
SORT_COLUMNS = {
    'date_desc':    Transaction.timestamp.desc(),
    'date_asc':     Transaction.timestamp.asc(),
    'amount_desc':  Transaction.amount.desc(),
    'amount_asc':   Transaction.amount.asc(),
    'category_asc': Transaction.category_name.asc(),
}

# --- AUTH ---

def check_auth(username, password):
    username_ok = hmac.compare_digest(username.encode('utf-8'), ADMIN_USERNAME.encode('utf-8'))
    password_ok = bcrypt.checkpw(password.encode('utf-8'), ADMIN_PASSWORD_HASH)
    # FIX: bitwise & (not 'and') — prevents short-circuit so bcrypt always runs,
    # eliminating the response-time difference that leaks whether the username is valid.
    return username_ok & password_ok

def requires_auth(f):
    """Decorator: redirects to login if there is no active session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# --- SHARED HELPERS ---

# DRY: currency conversion was duplicated in _handle_add_transaction and edit_expense
def _to_usd(amount, currency):
    d = Decimal(str(amount))
    if currency == 'KHR':
        return (d / KHR_TO_USD_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

# DRY: category upsert was duplicated in _handle_add_transaction, edit_expense, and migration
def _ensure_category(name, type_):
    if not Category.query.filter_by(name=name).first():
        try:
            # FIX: savepoint scopes the IntegrityError to this insert only;
            # a concurrent request racing to insert the same name won't roll back the outer transaction.
            with db.session.begin_nested():
                db.session.add(Category(name=name, type=type_))
        except IntegrityError:
            pass  # already inserted by a concurrent request; safe to ignore

def _archived_to_transaction(archived: 'DeletedTransaction') -> 'Transaction':
    """Reconstruct a Transaction row from a soft-deleted archive record."""
    return Transaction(
        id=archived.id, type=archived.type, name=archived.name,
        amount=archived.amount, currency=archived.currency,
        category_name=archived.category_name, timestamp=archived.timestamp,
        is_investment=archived.is_investment, note=archived.note,
        receipt_filename=archived.receipt_filename,
    )

# DRY: transaction serialization was duplicated in home() and export_data()
def _tx_to_dict(t):
    return {
        "id": t.id, "type": t.type, "name": t.name,
        "amount": float(t.amount),  # FIX: Decimal → float for JSON/JS compatibility
        "currency": t.currency, "category": t.category_name,
        "timestamp": t.timestamp, "is_investment": t.is_investment,
        "note": t.note or "",
        "has_receipt": bool(t.receipt_filename),
    }

def _parse_price(raw: str | None) -> float:
    """Parse a form price string to a non-negative float, defaulting to 0.0."""
    try:
        return max(0.0, float(raw) if raw else 0.0)
    except (ValueError, TypeError):
        return 0.0


def _parse_category_choice(form) -> str:
    """Resolve the category dropdown + optional new-category field to a category name."""
    choice = form.get('category_dropdown')
    if choice == ADD_NEW_SENTINEL:
        return form.get('new_category', '').strip().title()[:50] or DEFAULT_CATEGORY
    return choice[:50] if choice else DEFAULT_CATEGORY


def _parse_new_timestamp(user_date):
    """Return a full timestamp string from a date input, defaulting to now.

    Today's date gets the current wall-clock time.
    Past dates get 00:00:00 — preserving chronological ordering for backdated entries.
    """
    if user_date:
        try:
            dt = datetime.strptime(user_date, DATE_FORMAT)
            now = datetime.now()
            time_part = now.strftime('%H:%M:%S') if dt.date() == now.date() else '00:00:00'
            return f"{user_date} {time_part}"
        except ValueError:
            logger.warning("Invalid date '%s' submitted. Defaulting to now.", user_date)
    return datetime.now().strftime(TIMESTAMP_FORMAT)

# --- RECEIPT FILE HELPERS ---

def _detect_image_ext(header: bytes) -> str | None:
    """Return a file extension if the header bytes match a known image signature, else None."""
    for ext, (offset, sig) in ALLOWED_IMAGE_MAGIC.items():
        if header[offset:offset + len(sig)] == sig:
            return ext
    return None


def _delete_receipt(filename: str | None) -> None:
    """Remove a receipt file from disk if it exists. Silently ignores missing files."""
    if filename:
        path = os.path.join(RECEIPTS_DIR, filename)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _purge_archived(tx: 'DeletedTransaction') -> None:
    """Delete a soft-deleted transaction's receipt file and mark the DB row for deletion."""
    _delete_receipt(tx.receipt_filename)
    db.session.delete(tx)


def _save_receipt(tx_id: str, file) -> str | None:
    """Validate and persist an uploaded receipt image for the given transaction ID.

    Checks magic bytes (not just extension), enforces a 5 MB size cap, and saves
    the file as ``<tx_id>.<ext>`` so the filename is never user-controlled.

    Returns the saved filename on success, or None if the file is absent/invalid.
    """
    if not file or not file.filename:
        return None

    # Reject oversized uploads before reading the body — Content-Length can be spoofed,
    # so the byte-level size check below still runs as the authoritative guard.
    content_length = request.content_length
    if content_length and content_length > MAX_RECEIPT_BYTES:
        logger.warning("RECEIPT: Rejected upload for TX %s — Content-Length %d exceeds limit.", tx_id, content_length)
        return None

    header = file.read(12)
    ext = _detect_image_ext(header)
    if not ext:
        logger.warning("RECEIPT: Rejected upload for TX %s — unrecognized image format.", tx_id)
        return None

    # Measure full size: header already read, seek to end for remainder
    file.seek(0, 2)
    size = file.tell()
    if size > MAX_RECEIPT_BYTES:
        logger.warning("RECEIPT: Rejected upload for TX %s — size %d bytes exceeds limit.", tx_id, size)
        return None

    # Remove any existing receipt for this transaction before saving the new one
    for candidate_ext in ALLOWED_IMAGE_MAGIC:
        _delete_receipt(f"{tx_id}.{candidate_ext}")

    filename = f"{tx_id}.{ext}"
    file.seek(0)
    file.save(os.path.join(RECEIPTS_DIR, filename))
    logger.info("RECEIPT: Saved '%s' for TX %s.", filename, tx_id)
    return filename


# --- BUSINESS LOGIC HELPERS ---

# SRP: extracted from home() so the route doesn't compute budget math inline
def _get_budget_stats():
    settings = Setting.query.first()
    # target_savings_percentage is Numeric(5,2) → Decimal from SQLAlchemy; default to Decimal('0') if no settings row
    target_pct = settings.target_savings_percentage if settings else Decimal('0')
    total_income   = db.session.query(func.sum(Transaction.amount)).filter_by(type='income').scalar()  or Decimal('0')
    total_expenses = db.session.query(func.sum(Transaction.amount)).filter_by(type='expense').scalar() or Decimal('0')
    target_savings = (target_pct / 100) * total_income
    return {
        'total_income': total_income,
        'total_expenses': total_expenses,
        'target_savings': target_savings,
        'target_savings_percentage': target_pct,
        'budget': total_income - target_savings - total_expenses,
    }

# SRP + DRY: extracted from home(); inner _filter closure eliminates the repeated
# "if cutoff_str: query.filter(...)" pattern that appeared on every chart query
def _get_chart_data(cutoff_str, char_length):
    def _filter(q):
        return q.filter(Transaction.timestamp >= cutoff_str) if cutoff_str else q

    # FIX: float() wraps Decimal results so chart dicts are JSON-serialisable
    category_totals = {
        row[0]: float(row[1])
        for row in _filter(
            db.session.query(Transaction.category_name, func.sum(Transaction.amount))
            .filter(Transaction.type == 'expense')
        ).group_by(Transaction.category_name).all()
    }

    investment_totals = {"Investment": 0.0, "Sunk Cost": 0.0}
    for is_inv, amt in _filter(
        db.session.query(Transaction.is_investment, func.sum(Transaction.amount))
        .filter(Transaction.type == 'expense')
    ).group_by(Transaction.is_investment).all():
        investment_totals["Investment" if is_inv else "Sunk Cost"] += float(amt)

    income_category_totals = {
        row[0]: float(row[1])
        for row in _filter(
            db.session.query(Transaction.category_name, func.sum(Transaction.amount))
            .filter(Transaction.type == 'income')
        ).group_by(Transaction.category_name).all()
    }

    def _trend(tx_type):
        q = db.session.query(
            func.substr(Transaction.timestamp, 1, char_length).label('date_group'),
            func.sum(Transaction.amount),
        ).filter(Transaction.type == tx_type)
        return {row[0]: float(row[1]) for row in _filter(q).group_by('date_group').order_by('date_group').all()}

    return {
        'category_totals': category_totals,
        'investment_totals': investment_totals,
        'income_category_totals': income_category_totals,
        'trend_data': _trend('expense'),
        'income_trend_data': _trend('income'),
    }


def _build_tx_query(timeframe: str, sort_by: str, search_query: str, category_filter: str):
    """Build the filtered/sorted Transaction query for the home view.

    Returns (query, cutoff_str) where cutoff_str is None for all_time.
    Inputs are assumed already whitelist-validated by the caller.
    """
    cutoff_str = None
    if timeframe in TIMEFRAME_DELTAS:
        cutoff_str = (datetime.now() - TIMEFRAME_DELTAS[timeframe]).strftime(TIMESTAMP_FORMAT)

    q = Transaction.query
    if cutoff_str:
        q = q.filter(Transaction.timestamp >= cutoff_str)
    q = q.order_by(SORT_COLUMNS[sort_by])
    if search_query:
        q = q.filter(Transaction.name.ilike(f"%{search_query}%"))
    if category_filter and category_filter != 'all':
        q = q.filter(Transaction.category_name == category_filter)
    return q, cutoff_str


def _handle_add_transaction():
    """Parse, validate, and persist a new transaction from the add-transaction form. Returns True on success."""
    # KISS: collapsed double-assignment to single `or` expression
    expense_name = request.form.get('item_name', '').strip()[:100] or 'Unnamed Transaction'

    price = _parse_price(request.form.get('cost'))

    # FIX: whitelist-validate entry_type and currency before persisting
    entry_type = request.form.get('entry_type', 'expense')
    if entry_type not in VALID_ENTRY_TYPES:
        logger.warning("Invalid entry_type '%s' rejected.", entry_type)
        entry_type = 'expense'

    currency = request.form.get('currency', 'USD')
    if currency not in VALID_CURRENCIES:
        logger.warning("Invalid currency '%s' rejected.", currency)
        currency = 'USD'

    is_investment = request.form.get('is_investment') == 'on'
    category = _parse_category_choice(request.form)
    note = request.form.get('note', '').strip()[:1000]

    _ensure_category(category, entry_type)

    new_tx = Transaction(
        id=str(uuid.uuid4()),
        type=entry_type,
        name=expense_name,
        amount=_to_usd(price, currency),
        is_investment=is_investment,
        category_name=category,
        currency=currency,
        timestamp=_parse_new_timestamp(request.form.get('date')),
        note=note or None,
    )
    db.session.add(new_tx)
    new_tx.receipt_filename = _save_receipt(new_tx.id, request.files.get('receipt'))

    try:
        db.session.commit()
        logger.info("Transaction logged: %s | %s %s", expense_name, price, currency)
        return True
    except Exception:
        db.session.rollback()
        _delete_receipt(new_tx.receipt_filename)  # clean up file saved before the failed commit
        logger.exception("DATABASE ERROR: Failed to log '%s'.", expense_name)
        return False


# --- RECURRING TRANSACTION HELPERS ---

def _advance_next_due(frequency: str, current_due: str) -> str:
    """Return the next due date string after advancing by the given frequency."""
    dt = datetime.strptime(current_due, DATE_FORMAT)
    if frequency == 'daily':
        dt += timedelta(days=1)
    elif frequency == 'weekly':
        dt += timedelta(weeks=1)
    else:  # monthly
        dt += relativedelta(months=1)
    return dt.strftime(DATE_FORMAT)


_last_recurring_check: datetime | None = None


def _materialize_recurring() -> int:
    """Create Transaction rows for any recurring templates that are past due.

    Throttled to run at most once per 60 seconds to avoid a DB hit on every page load.
    Capped at 24 cycles per template to prevent runaway backfill.
    Returns the total number of transactions created.
    """
    global _last_recurring_check
    now = datetime.now()
    if _last_recurring_check and (now - _last_recurring_check).total_seconds() < 60:
        return 0
    _last_recurring_check = now

    today_str = now.strftime(DATE_FORMAT)
    templates = RecurringTransaction.query.all()
    count = 0
    for tmpl in templates:
        iterations = 0
        while tmpl.next_due <= today_str and iterations < 24:
            ts = f"{tmpl.next_due} {datetime.now().strftime('%H:%M:%S')}"
            tx = Transaction(
                id=str(uuid.uuid4()),
                type=tmpl.type,
                name=tmpl.name,
                amount=tmpl.amount,
                currency=tmpl.currency,
                category_name=tmpl.category_name,
                timestamp=ts,
                is_investment=tmpl.is_investment,
            )
            db.session.add(tx)
            _ensure_category(tmpl.category_name, tmpl.type)
            tmpl.next_due = _advance_next_due(tmpl.frequency, tmpl.next_due)
            count += 1
            iterations += 1
    if count > 0:
        try:
            db.session.commit()
            logger.info("RECURRING: Materialized %d transaction(s).", count)
        except Exception:
            db.session.rollback()
            logger.exception("RECURRING: Failed to materialize transactions.")
            count = 0
    return count


def _autopurge_trash(expiry_days: int) -> int:
    """Delete soft-deleted transactions older than expiry_days. Returns count purged."""
    cutoff_str = (datetime.now() - timedelta(days=expiry_days)).strftime(TIMESTAMP_FORMAT)
    expired = DeletedTransaction.query.filter(DeletedTransaction.deleted_at <= cutoff_str).all()
    if not expired:
        return 0
    for tx in expired:
        _purge_archived(tx)
    try:
        db.session.commit()
        logger.info("TRASH: Auto-purged %d expired transaction(s).", len(expired))
    except Exception:
        db.session.rollback()
        logger.exception("TRASH: Auto-purge failed.")
        return 0
    return len(expired)


def _get_envelope_data() -> list:
    """Return current-month spend vs. budget for every budgeted expense category.

    Returns a list of dicts sorted by spend percentage (highest first):
        [{"name": str, "budget": float, "spent": float, "pct": float}, ...]
    """
    month_prefix = datetime.now().strftime("%Y-%m")
    cats = (
        Category.query
        .filter(Category.monthly_budget != None, Category.type == 'expense')
        .order_by(Category.name)
        .all()
    )
    if not cats:
        return []

    names = [c.name for c in cats]
    budgets = {c.name: float(c.monthly_budget) for c in cats}

    spent_rows = (
        db.session.query(Transaction.category_name, func.sum(Transaction.amount))
        .filter(
            Transaction.type == 'expense',
            Transaction.category_name.in_(names),
            func.substr(Transaction.timestamp, 1, 7) == month_prefix,
        )
        .group_by(Transaction.category_name)
        .all()
    )
    spent = {row[0]: float(row[1]) for row in spent_rows}

    result = []
    for name in names:
        budget = budgets[name]
        s = spent.get(name, 0.0)
        pct = (s / budget * 100) if budget > 0 else 0.0
        result.append({"name": name, "budget": budget, "spent": s, "pct": round(pct, 1)})

    result.sort(key=lambda x: x['pct'], reverse=True)
    return result


def _rename_category(old_name: str, new_name: str) -> None:
    """Rename or merge a category across all referencing tables.

    If new_name already exists, the old category row is dropped (merge).
    Otherwise, the row is renamed in place.
    """
    Transaction.query.filter_by(category_name=old_name).update({"category_name": new_name})
    RecurringTransaction.query.filter_by(category_name=old_name).update({"category_name": new_name})
    if Category.query.filter_by(name=new_name).first():
        Category.query.filter_by(name=old_name).delete()
    else:
        Category.query.filter_by(name=old_name).update({"name": new_name})


def _migrate_database() -> None:
    """Apply schema migrations that db.create_all() cannot handle (new columns on existing tables)."""
    with db.engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(category)"))]
        if 'monthly_budget' not in cols:
            conn.execute(text("ALTER TABLE category ADD COLUMN monthly_budget NUMERIC(18,2)"))
            conn.commit()
            logger.info("MIGRATION: Added monthly_budget column to category table.")

        tx_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(\"transaction\")"))]
        if 'note' not in tx_cols:
            conn.execute(text("ALTER TABLE \"transaction\" ADD COLUMN note TEXT"))
            conn.commit()
            logger.info("MIGRATION: Added note column to transaction table.")
        if 'receipt_filename' not in tx_cols:
            conn.execute(text("ALTER TABLE \"transaction\" ADD COLUMN receipt_filename VARCHAR(255)"))
            conn.commit()
            logger.info("MIGRATION: Added receipt_filename column to transaction table.")

        setting_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(setting)"))]
        if 'trash_expiry_days' not in setting_cols:
            conn.execute(text("ALTER TABLE setting ADD COLUMN trash_expiry_days INTEGER DEFAULT 30"))
            conn.commit()
            logger.info("MIGRATION: Added trash_expiry_days column to setting table.")


# --- GLOBAL ERROR CATCHERS ---

@app.errorhandler(404)
def not_found_error(error):
    logger.warning("404: Attempted access to non-existent route -> %s", request.url)
    return "Page not found.", 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.critical("500 FATAL CRASH: Triggered by route -> %s", request.url)
    return "Internal Server Error. The admin has been notified in the logs.", 500

@app.errorhandler(429)
def ratelimit_handler(e):
    return render_template('429.html', error=e.description), 429


# --- SECURITY HEADERS ---

@app.after_request
def set_security_headers(response):
    # Prevent MIME-type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Clickjacking defence (belt + suspenders alongside CSP frame-ancestors)
    response.headers['X-Frame-Options'] = 'DENY'
    # FIX: CSP restricts what the browser will load and where forms may submit.
    # 'unsafe-inline' is required because all JS lives in inline <script> blocks.
    # Key wins even with 'unsafe-inline':
    #   - frame-ancestors 'none'  → blocks clickjacking in modern browsers
    #   - form-action 'self'      → prevents a compromised page from exfiltrating form data
    #   - connect-src 'self'      → blocks XHR/fetch to attacker-controlled hosts
    #   - base-uri 'self'         → prevents <base> injection that hijacks relative URLs
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response


# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    error = None
    if request.method == 'POST':
        # FIX: use .get() instead of [] to avoid KeyError on malformed requests
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if not check_auth(username, password):
            error = 'ACCESS DENIED. Invalid Credentials.'
        else:
            # Rotate the session ID before setting logged_in to prevent session fixation
            session.clear()
            session['logged_in'] = True
            # FIX: mark as permanent so PERMANENT_SESSION_LIFETIME is enforced
            session.permanent = True
            logger.info("SUCCESS: Admin logged in.")
            return redirect(url_for('home'))

    # THE BFCache KILLER: inject no-cache headers so the browser never snapshots this page
    resp = make_response(render_template('login.html', error=error))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# FIX: was GET — any <img src="/logout"> on any page would silently log the user out.
# Now POST-only, protected by CSRF token.
@app.route('/logout', methods=['POST'])
@requires_auth
def logout():
    # FIX: was session.pop('logged_in') — clear() removes all session data, not just one key
    session.clear()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@requires_auth
def home():
    if request.method == 'POST':
        # FIX: surface DB errors to the user instead of silently swallowing them
        if not _handle_add_transaction():
            flash('Transaction could not be saved. Check server logs.', 'error')
        return redirect('/')

    # 1. MATERIALIZE ANY DUE RECURRING TRANSACTIONS
    _materialize_recurring()

    # 2. BUDGET STATS
    stats = _get_budget_stats()

    # 3. VALIDATE AND PARSE FILTER / SORT PARAMS
    timeframe = request.args.get('timeframe', 'all_time')
    if timeframe != 'all_time' and timeframe not in TIMEFRAME_DELTAS:
        logger.warning("Invalid timeframe '%s' requested. Resetting to all_time.", timeframe)
        timeframe = 'all_time'

    sort_by = request.args.get('sort', 'date_desc')
    if sort_by not in SORT_COLUMNS:
        logger.warning("Invalid sort '%s' requested. Resetting to date_desc.", sort_by)
        sort_by = 'date_desc'

    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', 'all').strip()

    # 4. BUILD QUERY (timeframe / sort / search / category all handled in helper)
    tx_query, cutoff_str = _build_tx_query(timeframe, sort_by, search_query, category_filter)

    # 5. PAGINATION
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    pagination = tx_query.paginate(page=page, per_page=25, error_out=False)
    display_log = [_tx_to_dict(t) for t in pagination.items]

    # 6. CHART DATA
    char_length = TIMEFRAME_CHAR_LENGTHS.get(timeframe, 7)
    charts = _get_chart_data(cutoff_str, char_length)

    # 7. CATEGORY LISTS FOR DROPDOWNS
    expense_categories = [c.name for c in Category.query.filter_by(type='expense').order_by(Category.name).all()]
    income_categories = [c.name for c in Category.query.filter_by(type='income').order_by(Category.name).all()]

    # 8. BUDGET ENVELOPES
    envelopes = _get_envelope_data()

    return render_template(
        'index.html',
        expenses=display_log,
        expense_categories=expense_categories,
        income_categories=income_categories,
        current_sort=sort_by,
        current_timeframe=timeframe,
        pagination=pagination,
        current_category_filter=category_filter,
        current_search=search_query,
        envelopes=envelopes,
        now=datetime.now().strftime(TIMESTAMP_FORMAT),
        **stats,
        **charts,
    )

@app.route('/delete/<expense_id>', methods=['POST'])
@requires_auth
@limiter.limit("60 per minute")
def delete_expense(expense_id: str):
    """Soft-delete a transaction by archiving it in DeletedTransaction."""
    tx = db.session.get(Transaction, expense_id)
    if tx:
        archive = DeletedTransaction(
            id=tx.id, type=tx.type, name=tx.name,
            amount=tx.amount, currency=tx.currency,
            category_name=tx.category_name, timestamp=tx.timestamp,
            is_investment=tx.is_investment, note=tx.note,
            receipt_filename=tx.receipt_filename,
            deleted_at=datetime.now().strftime(TIMESTAMP_FORMAT),
        )
        db.session.add(archive)
        db.session.delete(tx)
        try:
            db.session.commit()
            logger.info("Transaction soft-deleted: ID %s", expense_id)
        except Exception:
            db.session.rollback()
            logger.exception("DELETE: Failed to soft-delete transaction %s.", expense_id)
    return redirect(url_for('home'))

@app.route('/edit/<expense_id>', methods=['POST'])
@requires_auth
@limiter.limit("60 per minute")
def edit_expense(expense_id):
    # FIX: Query.get() was deprecated in SQLAlchemy 2.0
    tx = db.session.get(Transaction, expense_id)
    if not tx:
        logger.warning("EDIT REJECTED: Transaction ID %s not found.", expense_id)
        return redirect(url_for('home'))

    # 1. NAME
    new_name = request.form.get('item_name', '').strip()[:100]
    if new_name:
        tx.name = new_name

    # 2. CATEGORY (DRY: uses ADD_NEW_SENTINEL constant and _ensure_category helper)
    category_choice = request.form.get('category_dropdown')
    if category_choice == ADD_NEW_SENTINEL:
        new_cat = request.form.get('new_category', '').strip().title()[:50]
        if new_cat:
            tx.category_name = new_cat
            _ensure_category(new_cat, tx.type)
    elif category_choice:
        # FIX: cap length and verify the category actually exists before assigning
        category_choice = category_choice[:50]
        if Category.query.filter_by(name=category_choice).first():
            tx.category_name = category_choice
        else:
            logger.warning("EDIT: Unknown category '%s' rejected for ID %s.", category_choice, expense_id)

    # 3. COST (DRY: uses _to_usd helper)
    raw_cost = request.form.get('cost')
    try:
        if raw_cost:
            currency = request.form.get('currency', 'USD')
            # FIX: validate currency against whitelist before storing
            if currency not in VALID_CURRENCIES:
                logger.warning("EDIT: Invalid currency '%s' rejected for ID %s.", currency, expense_id)
                currency = tx.currency
            tx.amount = _to_usd(float(raw_cost), currency)
            tx.currency = currency
    except (ValueError, TypeError):
        logger.error("EDIT FAILURE: Invalid cost '%s' for ID %s. Keeping original.", raw_cost, expense_id)

    # 4. DATE
    user_date = request.form.get('date')
    if user_date:
        try:
            datetime.strptime(user_date, DATE_FORMAT)
            old_time = tx.timestamp.split(" ")[1] if " " in tx.timestamp else datetime.now().strftime("%H:%M:%S")
            tx.timestamp = f"{user_date} {old_time}"
        except ValueError:
            logger.warning("EDIT: Invalid date '%s' for ID %s. Keeping original.", user_date, expense_id)

    tx.is_investment = request.form.get('is_investment') == 'on'

    # 5. NOTE
    note = request.form.get('note', '').strip()[:1000]
    tx.note = note or None

    # 6. RECEIPT — remove takes priority; otherwise replace if a new file was uploaded
    if request.form.get('remove_receipt') == 'on':
        _delete_receipt(tx.receipt_filename)
        tx.receipt_filename = None
    else:
        uploaded = request.files.get('receipt')
        if uploaded and uploaded.filename:
            new_filename = _save_receipt(tx.id, uploaded)
            if new_filename:
                tx.receipt_filename = new_filename

    try:
        db.session.commit()
        logger.info("Transaction %s updated.", expense_id)
    except Exception as e:
        db.session.rollback()
        logger.critical("DATABASE FATAL: Update failed for %s. Error: %s", expense_id, e)

    return redirect(url_for('home'))

@app.route('/categories', methods=['GET', 'POST'])
@requires_auth
@limiter.limit("30 per minute")  # FIX: missing rate limit; each POST can bulk-UPDATE many rows
def manage_categories():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            new_name = request.form.get('new_category_name', '').strip().title()[:50]
            if new_name and not Category.query.filter_by(name=new_name).first():
                budget = None
                raw_budget = request.form.get('monthly_budget', '').strip()
                if raw_budget:
                    try:
                        budget = Decimal(str(max(0.0, float(raw_budget)))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    except (ValueError, TypeError):
                        pass
                db.session.add(Category(name=new_name, type='expense', monthly_budget=budget))
                try:
                    db.session.commit()
                    logger.info("CAT_MGMT: Added category '%s'.", new_name)
                except Exception:
                    db.session.rollback()
                    logger.exception("CAT_MGMT: Failed to add category '%s'.", new_name)
            return redirect(url_for('manage_categories'))

        # FIX: guard against None/empty old_category and verify it's a real category
        old_category = request.form.get('old_category', '').strip()
        if not old_category or not Category.query.filter_by(name=old_category).first():
            logger.warning("CAT_MGMT: Unknown category '%s' rejected.", old_category)
            return redirect(url_for('manage_categories'))

        if action == 'delete':
            Transaction.query.filter_by(category_name=old_category).update({"category_name": DEFAULT_CATEGORY})
            RecurringTransaction.query.filter_by(category_name=old_category).update({"category_name": DEFAULT_CATEGORY})
            Category.query.filter_by(name=old_category).delete()
            try:
                db.session.commit()
                logger.info("CAT_MGMT: Deleted '%s'. Transactions moved to %s.", old_category, DEFAULT_CATEGORY)
            except Exception:
                db.session.rollback()
                logger.exception("CAT_MGMT: Failed to delete '%s'.", old_category)

        elif action == 'save':
            new_category = request.form.get('new_category', '').strip().title()[:50]
            if new_category and new_category != old_category:
                _rename_category(old_category, new_category)
                old_category = new_category
            cat = Category.query.filter_by(name=old_category).first()
            if cat:
                raw = request.form.get('monthly_budget', '').strip()
                if raw == '':
                    cat.monthly_budget = None
                else:
                    try:
                        val = float(raw)
                        cat.monthly_budget = Decimal(str(max(0.0, val))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    except (ValueError, TypeError):
                        logger.warning("BUDGET: Invalid budget value '%s' for '%s'.", raw, old_category)
            try:
                db.session.commit()
                logger.info("CAT_MGMT: Saved '%s' with budget update.", old_category)
            except Exception:
                db.session.rollback()
                logger.exception("CAT_MGMT: Failed to save '%s'.", old_category)

        return redirect(url_for('manage_categories'))

    categories = Category.query.order_by(Category.name).all()
    return render_template('categories.html', categories=categories)

@app.route('/update_savings', methods=['POST'])
@requires_auth
@limiter.limit("20 per minute")
def update_savings():
    settings_obj = Setting.query.first()
    if not settings_obj:
        settings_obj = Setting(target_savings_percentage=0.0)
        db.session.add(settings_obj)

    try:
        raw_percentage = request.form.get('target_savings_percentage')
        new_val = float(raw_percentage) if raw_percentage else 0.0
        settings_obj.target_savings_percentage = Decimal(str(max(0.0, min(100.0, new_val)))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        db.session.commit()
        logger.info("SETTINGS: Savings target updated to %s%%", settings_obj.target_savings_percentage)
    except (ValueError, TypeError):
        logger.warning("SETTINGS ERROR: Invalid percentage '%s' submitted.", raw_percentage)
        db.session.rollback()

    return redirect(url_for('home'))

@app.route('/export_data', methods=['GET'])
@requires_auth
@limiter.limit("10 per minute")
def export_data():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"wealth_engine_backup_{timestamp}.json"
    logger.info("SECURITY EVENT: Admin triggered full database export -> %s", filename)

    # FIX: was .all() which loads every row into memory at once.
    # Generator + yield_per streams the response in chunks.
    def generate():
        yield '[\n'
        first = True
        for t in Transaction.query.order_by(Transaction.timestamp.asc()).yield_per(200):
            if not first:
                yield ',\n'
            yield json.dumps(_tx_to_dict(t), indent=4)
            first = False
        yield '\n]'

    return Response(
        generate(),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment;filename={filename}'}
    )


@app.route('/recurring', methods=['GET', 'POST'])
@requires_auth
@limiter.limit("30 per minute")
def manage_recurring():
    if request.method == 'POST':
        name = request.form.get('item_name', '').strip()[:100] or 'Unnamed'

        price = _parse_price(request.form.get('cost'))

        entry_type = request.form.get('entry_type', 'expense')
        if entry_type not in VALID_ENTRY_TYPES:
            entry_type = 'expense'

        currency = request.form.get('currency', 'USD')
        if currency not in VALID_CURRENCIES:
            currency = 'USD'

        frequency = request.form.get('frequency', 'monthly')
        if frequency not in VALID_FREQUENCIES:
            frequency = 'monthly'

        is_investment = request.form.get('is_investment') == 'on'
        category = _parse_category_choice(request.form)

        start_date = request.form.get('start_date', '').strip()
        try:
            datetime.strptime(start_date, DATE_FORMAT)
        except (ValueError, TypeError):
            start_date = datetime.now().strftime(DATE_FORMAT)

        _ensure_category(category, entry_type)
        tmpl = RecurringTransaction(
            name=name,
            amount=_to_usd(price, currency),
            currency=currency,
            type=entry_type,
            category_name=category,
            is_investment=is_investment,
            frequency=frequency,
            next_due=start_date,
        )
        db.session.add(tmpl)
        try:
            db.session.commit()
            logger.info("RECURRING: Template '%s' created (%s %s).", name, frequency, entry_type)
        except Exception:
            db.session.rollback()
            logger.exception("RECURRING: Failed to create template '%s'.", name)

        return redirect(url_for('manage_recurring'))

    templates = RecurringTransaction.query.order_by(RecurringTransaction.name).all()
    expense_categories = [c.name for c in Category.query.filter_by(type='expense').order_by(Category.name).all()]
    income_categories = [c.name for c in Category.query.filter_by(type='income').order_by(Category.name).all()]
    return render_template(
        'recurring.html',
        templates=templates,
        expense_categories=expense_categories,
        income_categories=income_categories,
    )


@app.route('/recurring/delete/<int:tmpl_id>', methods=['POST'])
@requires_auth
@limiter.limit("30 per minute")
def delete_recurring(tmpl_id):
    tmpl = db.session.get(RecurringTransaction, tmpl_id)
    if tmpl:
        db.session.delete(tmpl)
        try:
            db.session.commit()
            logger.info("RECURRING: Template ID %d deleted.", tmpl_id)
        except Exception:
            db.session.rollback()
            logger.exception("RECURRING: Failed to delete template ID %d.", tmpl_id)
    return redirect(url_for('manage_recurring'))


@app.route('/trash', methods=['GET'])
@requires_auth
@limiter.limit("30 per minute")
def trash() -> str:
    """Display all soft-deleted transactions, newest first. Auto-purges expired items first."""
    settings = Setting.query.first()
    expiry_days = settings.trash_expiry_days if settings and settings.trash_expiry_days else 30
    _autopurge_trash(expiry_days)
    deleted = DeletedTransaction.query.order_by(DeletedTransaction.deleted_at.desc()).all()
    return render_template('trash.html', deleted=deleted, expiry_days=expiry_days)


@app.route('/trash/restore/<tx_id>', methods=['POST'])
@requires_auth
@limiter.limit("30 per minute")
def restore_transaction(tx_id: str):
    """Move a soft-deleted transaction back to the main Transaction table."""
    archived = db.session.get(DeletedTransaction, tx_id)
    if archived:
        _ensure_category(archived.category_name, archived.type)
        db.session.add(_archived_to_transaction(archived))
        db.session.delete(archived)
        try:
            db.session.commit()
            logger.info("Transaction restored: ID %s", tx_id)
        except Exception:
            db.session.rollback()
            logger.exception("RESTORE: Failed to restore transaction %s.", tx_id)
    return redirect(url_for('trash'))


@app.route('/trash/purge/<tx_id>', methods=['POST'])
@requires_auth
@limiter.limit("30 per minute")
def purge_transaction(tx_id: str):
    """Permanently delete a soft-deleted transaction and its receipt file."""
    archived = db.session.get(DeletedTransaction, tx_id)
    if archived:
        _purge_archived(archived)
        db.session.commit()
        logger.info("Transaction permanently purged: ID %s", tx_id)
    return redirect(url_for('trash'))


@app.route('/trash/purge-all', methods=['POST'])
@requires_auth
@limiter.limit("10 per minute")
def purge_all_transactions():
    """Permanently delete every item in trash, including receipt files."""
    count = 0
    for tx in DeletedTransaction.query.yield_per(200):
        _purge_archived(tx)
        count += 1
    if count:
        try:
            db.session.commit()
            logger.info("TRASH: Purged all %d transaction(s).", count)
        except Exception:
            db.session.rollback()
            logger.exception("TRASH: Purge-all failed.")
    return redirect(url_for('trash'))


@app.route('/trash/update-expiry', methods=['POST'])
@requires_auth
@limiter.limit("20 per minute")
def update_trash_expiry():
    """Update the auto-purge expiry period stored in Settings."""
    settings = Setting.query.first()
    if not settings:
        settings = Setting(target_savings_percentage=0.0, trash_expiry_days=30)
        db.session.add(settings)
    try:
        raw = request.form.get('trash_expiry_days', '30')
        settings.trash_expiry_days = max(1, min(365, int(raw)))
        db.session.commit()
        logger.info("TRASH: Expiry period set to %d day(s).", settings.trash_expiry_days)
    except (ValueError, TypeError):
        logger.warning("TRASH: Invalid expiry value '%s' rejected.", request.form.get('trash_expiry_days'))
        db.session.rollback()
    return redirect(url_for('trash'))


@app.route('/trash/bulk', methods=['POST'])
@requires_auth
@limiter.limit("20 per minute")
def bulk_trash_action():
    """Bulk restore or permanently purge a selection of soft-deleted transactions."""
    action = request.form.get('bulk_action')
    tx_ids = request.form.getlist('tx_ids')[:500]  # hard cap — prevents DoS via oversized payload
    if action not in ('restore', 'purge') or not tx_ids:
        return redirect(url_for('trash'))

    archived_list = DeletedTransaction.query.filter(DeletedTransaction.id.in_(tx_ids)).all()

    if action == 'restore':
        for archived in archived_list:
            _ensure_category(archived.category_name, archived.type)
            db.session.add(_archived_to_transaction(archived))
            db.session.delete(archived)
        try:
            db.session.commit()
            logger.info("TRASH: Bulk restored %d transaction(s).", len(archived_list))
        except Exception:
            db.session.rollback()
            logger.exception("TRASH: Bulk restore failed.")

    elif action == 'purge':
        for archived in archived_list:
            _purge_archived(archived)
        try:
            db.session.commit()
            logger.info("TRASH: Bulk purged %d transaction(s).", len(archived_list))
        except Exception:
            db.session.rollback()
            logger.exception("TRASH: Bulk purge failed.")

    return redirect(url_for('trash'))


@app.route('/receipt/<tx_id>')
@requires_auth
@limiter.limit("60 per minute")
def serve_receipt(tx_id: str):
    """Serve a receipt image for the given transaction ID (auth-gated)."""
    tx = db.session.get(Transaction, tx_id)
    if not tx or not tx.receipt_filename:
        abort(404)
    return send_file(os.path.join(RECEIPTS_DIR, tx.receipt_filename))


VALID_NW_TYPES      = {'asset', 'liability'}
VALID_NW_CATEGORIES = {'bank', 'investment', 'property', 'loan', 'credit', 'other'}


@app.route('/net-worth', methods=['GET', 'POST'])
@requires_auth
@limiter.limit("30 per minute")
def net_worth():
    """Display and manage net worth items (assets and liabilities)."""
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'add':
            name = request.form.get('item_name', '').strip()[:100] or 'Unnamed'
            item_type = request.form.get('item_type', 'asset')
            if item_type not in VALID_NW_TYPES:
                item_type = 'asset'
            category = request.form.get('category', 'other')
            if category not in VALID_NW_CATEGORIES:
                category = 'other'
            last_updated = request.form.get('last_updated', datetime.now().strftime(DATE_FORMAT))
            try:
                datetime.strptime(last_updated, DATE_FORMAT)
            except ValueError:
                last_updated = datetime.now().strftime(DATE_FORMAT)
            try:
                balance = max(Decimal('0'), Decimal(str(request.form.get('balance', '0'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            except Exception:
                balance = Decimal('0')
            db.session.add(NetWorthItem(
                name=name, item_type=item_type, category=category,
                balance=balance, last_updated=last_updated,
            ))
            try:
                db.session.commit()
                logger.info("NET WORTH: Added '%s' (%s / %s) = $%s", name, item_type, category, balance)
            except Exception:
                db.session.rollback()
                logger.exception("NET WORTH: Failed to add '%s'.", name)

        elif action == 'edit':
            try:
                item_id = int(request.form.get('item_id', ''))
            except (ValueError, TypeError):
                return redirect(url_for('net_worth'))
            item = db.session.get(NetWorthItem, item_id)
            if item:
                item.name = request.form.get('item_name', item.name).strip()[:100] or item.name
                new_type = request.form.get('item_type', item.item_type)
                if new_type in VALID_NW_TYPES:
                    item.item_type = new_type
                new_cat = request.form.get('category', item.category)
                if new_cat in VALID_NW_CATEGORIES:
                    item.category = new_cat
                try:
                    raw = request.form.get('balance', '')
                    item.balance = max(Decimal('0'), Decimal(str(raw)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                except Exception:
                    pass
                raw_date = request.form.get('last_updated', '')
                try:
                    datetime.strptime(raw_date, DATE_FORMAT)
                    item.last_updated = raw_date
                except ValueError:
                    pass
                try:
                    db.session.commit()
                    logger.info("NET WORTH: Updated item %s.", item_id)
                except Exception:
                    db.session.rollback()
                    logger.exception("NET WORTH: Failed to update item %s.", item_id)

        elif action == 'delete':
            try:
                item_id = int(request.form.get('item_id', ''))
            except (ValueError, TypeError):
                return redirect(url_for('net_worth'))
            item = db.session.get(NetWorthItem, item_id)
            if item:
                db.session.delete(item)
                try:
                    db.session.commit()
                    logger.info("NET WORTH: Deleted item %s.", item_id)
                except Exception:
                    db.session.rollback()
                    logger.exception("NET WORTH: Failed to delete item %s.", item_id)

        return redirect(url_for('net_worth'))

    assets      = NetWorthItem.query.filter_by(item_type='asset').order_by(NetWorthItem.name).all()
    liabilities = NetWorthItem.query.filter_by(item_type='liability').order_by(NetWorthItem.name).all()
    total_assets      = sum(item.balance for item in assets)      or Decimal('0')
    total_liabilities = sum(item.balance for item in liabilities) or Decimal('0')
    net_worth_value   = total_assets - total_liabilities
    investment_total = (
        db.session.query(func.sum(Transaction.amount))
        .filter(Transaction.type == 'expense', Transaction.is_investment == True)  # noqa: E712
        .scalar()
    ) or Decimal('0')
    return render_template(
        'net_worth.html',
        assets=assets,
        liabilities=liabilities,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        net_worth_value=net_worth_value,
        investment_total=investment_total,
        nw_categories=sorted(VALID_NW_CATEGORIES),
        today=datetime.now().strftime(DATE_FORMAT),
    )


# Initialize the database and migrate existing JSON data if needed
with app.app_context():
    db.create_all()
    _migrate_database()

    if not Setting.query.first():
        try:
            with open("settings.json", "r") as file:
                data = json.load(file)
                db.session.add(Setting(target_savings_percentage=data.get("target_savings_percentage", 0)))
                db.session.commit()
                logger.info("Settings migrated to SQL.")
        except FileNotFoundError:
            db.session.add(Setting(target_savings_percentage=0))
            db.session.commit()

    if not Transaction.query.first():
        try:
            with open("expense_log.json", "r") as file:
                for item in json.load(file):
                    cat_name = item.get("category", DEFAULT_CATEGORY)
                    cat_type = item.get("type", "expense")
                    db.session.add(Transaction(
                        id=item.get("id", str(uuid.uuid4())),
                        type=cat_type,
                        name=item.get("name", "Unnamed"),
                        amount=item.get("amount", 0),
                        currency=item.get("currency", "USD"),
                        category_name=cat_name,
                        timestamp=item.get("timestamp", datetime.now().strftime(TIMESTAMP_FORMAT)),
                        is_investment=item.get("is_investment", False),
                    ))
                    # DRY: uses _ensure_category helper instead of inline check
                    _ensure_category(cat_name, cat_type)
                db.session.commit()
                logger.info("All JSON transactions and categories migrated to SQL.")
        except FileNotFoundError:
            pass

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')
