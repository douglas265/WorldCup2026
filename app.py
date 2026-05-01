from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fbd0fc8f44a13bf61a5d88fd8bddc79e8e59dd59fbfbf55ac83ac66216e3b8ae')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///worldcup2026.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Flask-Mail (Gmail)
app.config['MAIL_SERVER']   = 'smtp.gmail.com'
app.config['MAIL_PORT']     = 587
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')   # your Gmail address
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')   # your App Password
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

@app.template_filter('flag_html')
def flag_html_filter(val):
    if not val:
        return ''
    val = val.strip()
    # Convert flag emoji (🇺🇸) to 2-letter code (us)
    if len(val) == 2 and not val.isascii():
        try:
            code = ''.join(chr(ord(c) - 0x1F1A5) for c in val).lower()
        except Exception:
            return val
    else:
        code = val.lower()
    return f'<img src="https://cdn.jsdelivr.net/npm/flag-icons@7.2.3/flags/4x3/{code}.svg" alt="{code.upper()}" style="height:15px;vertical-align:middle;border-radius:2px;">'


@app.template_filter('to_pt')
def to_pt_filter(dt):
    if not dt:
        return ''
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    pacific = ZoneInfo('America/Los_Angeles')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(pacific)
    return local.strftime('%a, %b %d %Y — %I:%M %p PT')

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

BET_AMOUNT = 5.0  # Fixed cost per bet in dollars


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    balance = db.Column(db.Float, default=0.0)
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))
    payment_method = db.Column(db.String(16))   # 'venmo' | 'zelle'
    payment_handle = db.Column(db.String(128))  # their @venmo or phone/email for zelle
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    bets = db.relationship('Bet', backref='user', lazy=True)
    tournament_bet = db.relationship('TournamentBet', backref='user', uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def total_points(self):
        match_pts = sum(b.points for b in self.bets if b.points is not None)
        tourney_pts = self.tournament_bet.points if self.tournament_bet and self.tournament_bet.points else 0
        return match_pts + tourney_pts


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    group = db.Column(db.String(4))
    flag_emoji = db.Column(db.String(8), default='🏳')

    def __repr__(self):
        return self.name


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # nullable=True for knockout rounds where teams are TBD
    home_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    away_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    match_date = db.Column(db.DateTime, nullable=True)
    stage = db.Column(db.String(32), default='Group Stage')
    venue = db.Column(db.String(64))
    # result: 'home', 'draw', 'away', or None if not played
    result = db.Column(db.String(8))
    home_score = db.Column(db.Integer)
    away_score = db.Column(db.Integer)
    is_locked = db.Column(db.Boolean, default=False)

    # Bracket fields (null for group stage matches)
    bracket_slot     = db.Column(db.String(16))  # "R32-01", "R16-03", "QF-02", "SF-01", "3RD", "FINAL"
    home_source      = db.Column(db.String(16))  # "1A", "T3-1" for R32; None for later rounds
    away_source      = db.Column(db.String(16))
    winner_next_slot = db.Column(db.String(16))  # bracket_slot of where winner advances
    winner_next_pos  = db.Column(db.String(4))   # 'home' or 'away'
    loser_next_slot  = db.Column(db.String(16))  # SF only: loser goes to 3rd place
    loser_next_pos   = db.Column(db.String(4))

    home_team = db.relationship('Team', foreign_keys=[home_team_id])
    away_team = db.relationship('Team', foreign_keys=[away_team_id])
    bets = db.relationship('Bet', backref='match', lazy=True)

    def has_teams(self):
        return self.home_team_id is not None and self.away_team_id is not None

    def betting_open(self):
        if self.is_locked or self.result is not None or not self.has_teams():
            return False
        if self.match_date:
            match_dt = self.match_date
            if match_dt.tzinfo is None:
                match_dt = match_dt.replace(tzinfo=timezone.utc)
            return (match_dt - datetime.now(timezone.utc)).total_seconds() > 12 * 3600
        return True

    def hours_until_kickoff(self):
        """Returns hours until match (negative if past). None if no date set."""
        if not self.match_date:
            return None
        match_dt = self.match_date
        if match_dt.tzinfo is None:
            match_dt = match_dt.replace(tzinfo=timezone.utc)
        return (match_dt - datetime.now(timezone.utc)).total_seconds() / 3600

    @property
    def is_knockout(self):
        return self.stage in (
            'Round of 32', 'Round of 16', 'Quarter-Final',
            'Semi-Final', '3rd Place', 'Final'
        )

    def home_label(self):
        if self.home_team:
            return f"{self.home_team.flag_emoji} {self.home_team.name}"
        return self.home_source or 'TBD'

    def away_label(self):
        if self.away_team:
            return f"{self.away_team.name} {self.away_team.flag_emoji}"
        return self.away_source or 'TBD'

    def display_result(self):
        if self.home_score is not None and self.away_score is not None:
            return f"{self.home_score} - {self.away_score}"
        return "vs"


class Bet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    # prediction: 'home', 'draw', 'away'
    prediction = db.Column(db.String(8), nullable=False)
    points = db.Column(db.Integer)       # None until result; 3 if correct, 0 if wrong
    amount = db.Column(db.Float, default=BET_AMOUNT)
    payout = db.Column(db.Float)         # None=pending, 0.0=lost, >0=won or refunded
    placed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('user_id', 'match_id'),)

    def status(self):
        if self.payout is None:
            return 'pending'
        if self.payout == 0.0:
            return 'lost'
        if abs(self.payout - (self.amount or BET_AMOUNT)) < 0.01:
            return 'refunded'
        return 'won'

    def net(self):
        """Net gain/loss. None while pending."""
        if self.payout is None:
            return None
        return round(self.payout - (self.amount or BET_AMOUNT), 2)


class Transaction(db.Model):
    """Full ledger of every balance change for a user."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)     # positive = money in, negative = money out
    balance_after = db.Column(db.Float, nullable=False)
    tx_type = db.Column(db.String(32), nullable=False)
    # tx_type values: admin_credit, admin_debit,
    #                 bet_placed, bet_removed,
    #                 match_won, match_lost, match_refunded
    description = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='transactions')


def record_tx(user, amount, tx_type, description):
    """Update user balance and write a Transaction row. Does NOT commit."""
    user.balance = round(user.balance + amount, 2)
    tx = Transaction(
        user_id=user.id,
        amount=amount,
        balance_after=user.balance,
        tx_type=tx_type,
        description=description,
    )
    db.session.add(tx)
    return tx


TOURNAMENT_BET_AMOUNT = 20.0

class TournamentBet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    points = db.Column(db.Integer)  # 10 if correct
    amount = db.Column(db.Float, default=20.0)
    payout = db.Column(db.Float)    # None=pending, 0=lost, >0=won/refunded
    placed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    team = db.relationship('Team')


class PayoutRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(16), default='pending')  # 'pending' | 'paid'
    requested_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    paid_at = db.Column(db.DateTime)

    user = db.relationship('User', backref='payout_requests')


class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    user = db.relationship('User')



@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        payment_method = request.form.get('payment_method', '').strip()
        payment_handle = request.form.get('payment_handle', '').strip()

        error = None
        if not username or not email or not password:
            error = 'All fields are required.'
        elif not first_name or not last_name:
            error = 'First and last name are required.'
        elif password != confirm:
            error = 'Passwords do not match.'
        elif User.query.filter_by(username=username).first():
            error = 'Username already taken.'
        elif User.query.filter_by(email=email).first():
            error = 'Email already registered.'

        if error:
            flash(error, 'danger')
        else:
            user = User(username=username, email=email,
                        first_name=first_name, last_name=last_name,
                        payment_method=payment_method or None,
                        payment_handle=payment_handle or None)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Welcome! You are now registered.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        user = (User.query.filter_by(email=identifier.lower()).first()
                or User.query.filter_by(username=identifier).first())
        if user:
            import secrets
            from datetime import timedelta
            PasswordReset.query.filter_by(user_id=user.id, used=False).update({'used': True})
            token = secrets.token_urlsafe(32)
            pr = PasswordReset(
                user_id=user.id,
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.session.add(pr)
            db.session.commit()
            reset_url = url_for('reset_password', token=token, _external=True)
            try:
                msg = Message(
                    subject='WC2026 Folsom — Password Reset',
                    recipients=[user.email],
                    html=f'''
                        <p>Hi {user.first_name or user.username},</p>
                        <p>Click the link below to reset your password. It expires in <strong>1 hour</strong>.</p>
                        <p><a href="{reset_url}" style="background:#1a7a3e;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">Reset My Password</a></p>
                        <p style="color:#888;font-size:12px">Or copy this URL: {reset_url}</p>
                        <p style="color:#888;font-size:12px">If you didn't request this, ignore this email.</p>
                    '''
                )
                mail.send(msg)
                flash(f'Reset email sent to {user.email}.', 'success')
            except Exception as e:
                app.logger.error(f'Mail send failed: {e}')
                flash('Could not send email. Contact the admin for help.', 'danger')
        else:
            # Don't reveal whether the account exists
            flash('If that account exists, a reset email has been sent.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    pr = PasswordReset.query.filter_by(token=token, used=False).first()
    if not pr or pr.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        flash('This reset link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        else:
            pr.user.set_password(password)
            pr.used = True
            db.session.commit()
            flash('Password updated! You can now log in.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)

# ---------------------------------------------------------------------------
# ESPN sync helpers
# ---------------------------------------------------------------------------

ESPN_TEAM_MAP = {
    'Korea Republic':           'South Korea',
    'Czech Republic':           'Czechia',
    'Turkey':                   'Turkiye',
    "Côte d'Ivoire":            'Ivory Coast',
    'USA':                      'United States',
    'Bosnia and Herzegovina':   'Bosnia-Herzegovina',
    'IR Iran':                  'Iran',
    'Kyrgyz Republic':          'Kyrgyzstan',
    'Trinidad and Tobago':      'Trinidad & Tobago',
    'St. Kitts and Nevis':      'Saint Kitts and Nevis',
    'Cape Verde':               'Cabo Verde',
    'Congo DR':                 'DR Congo',
    'Congo':                    'Congo',
}

ESPN_FINAL_STATUSES = {'STATUS_FINAL', 'STATUS_FINAL_AET', 'STATUS_FINAL_PEN'}


def _do_espn_sync():
    """Fetch ESPN scoreboard for today and yesterday, apply any new final results.
    Returns (synced_count, skipped_count, error_messages).
    Safe to call from both the admin route and the background scheduler."""
    try:
        import requests as _req
    except ImportError:
        return 0, 0, ['requests library not installed']

    from datetime import date, timedelta
    synced, skipped, errors = 0, 0, []
    today = date.today()

    for delta in (1, 0):
        check_date = today - timedelta(days=delta)
        date_str = check_date.strftime('%Y%m%d')
        url = (f'https://site.api.espn.com/apis/site/v2/sports/soccer'
               f'/fifa.world/scoreboard?dates={date_str}')
        try:
            resp = _req.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            errors.append(f'ESPN fetch failed for {check_date}: {exc}')
            continue

        for event in data.get('events', []):
            comp        = event.get('competitions', [{}])[0]
            status_name = comp.get('status', {}).get('type', {}).get('name', '')
            if status_name not in ESPN_FINAL_STATUSES:
                continue

            competitors = comp.get('competitors', [])
            home_comp = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away_comp = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            if not home_comp or not away_comp:
                continue

            raw_home  = home_comp.get('team', {}).get('displayName', '')
            raw_away  = away_comp.get('team', {}).get('displayName', '')
            home_name = ESPN_TEAM_MAP.get(raw_home, raw_home)
            away_name = ESPN_TEAM_MAP.get(raw_away, raw_away)

            try:
                home_score = int(home_comp.get('score', 0))
                away_score = int(away_comp.get('score', 0))
            except (ValueError, TypeError):
                continue

            home_team = Team.query.filter(Team.name.ilike(home_name)).first()
            away_team = Team.query.filter(Team.name.ilike(away_name)).first()
            if not home_team or not away_team:
                skipped += 1
                continue

            match = Match.query.filter_by(
                home_team_id=home_team.id,
                away_team_id=away_team.id
            ).first()
            if not match or match.result:
                skipped += 1
                continue

            if home_score > away_score:
                result = 'home'
            elif away_score > home_score:
                result = 'away'
            else:
                # Scores level after 90 min.
                # STATUS_FINAL_PEN: ESPN marks the pen winner with winner=True.
                # STATUS_FINAL_AET with a level score shouldn't occur (ET goal
                # would change the score), but treat it like a group draw.
                if status_name == 'STATUS_FINAL_PEN':
                    if home_comp.get('winner'):
                        result = 'home'
                    elif away_comp.get('winner'):
                        result = 'away'
                    else:
                        skipped += 1
                        continue
                elif match.is_knockout:
                    skipped += 1
                    continue
                else:
                    result = 'draw'

            _apply_match_result(match, home_score, away_score, result)
            db.session.commit()
            from bracket import advance_bracket
            advance_bracket()
            synced += 1

    return synced, skipped, errors


def _apply_match_result(match, home_score, away_score, result):
    """Set scores/result, award bet points, distribute pool payouts.
    Caller must commit after calling this."""
    match.result = result
    match.home_score = home_score
    match.away_score = away_score
    match.is_locked = True

    for bet in match.bets:
        bet.points = 3 if bet.prediction == result else 0

    bets = match.bets
    if bets:
        home_name = match.home_team.name if match.home_team else (match.home_source or 'Home')
        away_name = match.away_team.name if match.away_team else (match.away_source or 'Away')
        match_label = f'{home_name} vs {away_name}'
        total_pool = round(sum(b.amount or BET_AMOUNT for b in bets), 2)
        winners = [b for b in bets if b.prediction == result]
        if winners:
            payout_each = round(total_pool / len(winners), 2)
            for bet in bets:
                if bet.prediction == result:
                    bet.payout = payout_each
                    record_tx(bet.user, payout_each, 'match_won',
                              f'Won: {match_label} — ${payout_each:.2f} '
                              f'(pool ${total_pool:.2f} ÷ {len(winners)} winner{"s" if len(winners)>1 else ""})')
                else:
                    bet.payout = 0.0
                    record_tx(bet.user, 0.0, 'match_lost', f'Lost: {match_label}')
        else:
            for bet in bets:
                bet.payout = bet.amount or BET_AMOUNT
                record_tx(bet.user, bet.payout, 'match_refunded',
                          f'Refund: {match_label} — no winners')

    if match.bracket_slot == 'FINAL':
        winner_team_id = (match.home_team_id if result == 'home' else match.away_team_id)
        winner_team = db.session.get(Team, winner_team_id)
        all_tbs = TournamentBet.query.filter(TournamentBet.payout.is_(None)).all()
        if all_tbs:
            total_tb_pool = round(sum(tb.amount or TOURNAMENT_BET_AMOUNT for tb in all_tbs), 2)
            tb_winners = [tb for tb in all_tbs if tb.team_id == winner_team_id]
            champ_label = winner_team.name if winner_team else 'Champion'
            if tb_winners:
                tb_payout = round(total_tb_pool / len(tb_winners), 2)
                for tb in all_tbs:
                    if tb.team_id == winner_team_id:
                        tb.payout = tb_payout
                        tb.points = 10
                        record_tx(tb.user, tb_payout, 'match_won',
                                  f'Champion pick correct: {champ_label} — ${tb_payout:.2f}')
                    else:
                        tb.payout = 0.0
                        tb.points = 0
                        record_tx(tb.user, 0.0, 'match_lost',
                                  f'Champion pick wrong (winner: {champ_label})')
            else:
                for tb in all_tbs:
                    tb.payout = tb.amount or TOURNAMENT_BET_AMOUNT
                    tb.points = 0
                    record_tx(tb.user, tb.payout, 'match_refunded',
                              f'Champion pick refund — no one picked {champ_label}')


# ---------------------------------------------------------------------------
# User routes
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def dashboard():
    upcoming = (Match.query
                .filter(Match.result.is_(None))
                .filter(Match.home_team_id.isnot(None))
                .filter(Match.away_team_id.isnot(None))
                .order_by(Match.match_date)
                .limit(5).all())
    my_bets = {b.match_id: b for b in current_user.bets}
    leaderboard = User.query.filter_by(is_admin=False).all()
    leaderboard.sort(key=lambda u: u.total_points(), reverse=True)
    leaderboard = leaderboard[:10]
    return render_template('dashboard.html', upcoming=upcoming,
                           my_bets=my_bets, leaderboard=leaderboard)


@app.route('/matches')
@login_required
def matches():
    stage = request.args.get('stage', 'all')
    team_id = request.args.get('team', type=int)
    q = Match.query.order_by(Match.match_date)
    if stage != 'all':
        q = q.filter(Match.stage == stage)
    if team_id:
        q = q.filter(
            db.or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
        )
    all_matches = q.all()
    my_bets = {b.match_id: b for b in current_user.bets}
    stages = db.session.query(Match.stage).distinct().all()
    stages = [s[0] for s in stages]
    teams = Team.query.order_by(Team.group, Team.name).all()

    # Bet distribution per match
    match_ids = [m.id for m in all_matches]
    bet_dist = {}
    match_bets = {}
    if match_ids:
        rows = db.session.query(Bet.match_id, Bet.prediction, db.func.count(Bet.id))\
            .filter(Bet.match_id.in_(match_ids))\
            .group_by(Bet.match_id, Bet.prediction).all()
        for mid, pred, cnt in rows:
            bet_dist.setdefault(mid, {'home': 0, 'draw': 0, 'away': 0})[pred] = cnt

        finished_ids = [m.id for m in all_matches if m.result]
        if finished_ids:
            bets = Bet.query.filter(Bet.match_id.in_(finished_ids))\
                .order_by(Bet.match_id, Bet.payout.desc().nullslast())\
                .all()
            for b in bets:
                match_bets.setdefault(b.match_id, []).append(b)

    return render_template('matches.html', matches=all_matches,
                           my_bets=my_bets, stages=stages, current_stage=stage,
                           teams=teams, current_team=team_id,
                           bet_dist=bet_dist, match_bets=match_bets)


@app.route('/bet/<int:match_id>', methods=['POST'])
@login_required
def place_bet(match_id):
    match = db.session.get(Match, match_id)
    if not match:
        abort(404)
    if not match.betting_open():
        flash('Betting is closed for this match.', 'warning')
        return redirect(url_for('matches'))

    prediction = request.form.get('prediction')

    # Allow user to remove their existing bet
    if prediction == 'none':
        existing = Bet.query.filter_by(user_id=current_user.id, match_id=match_id).first()
        if existing:
            home = match.home_team.name if match.home_team else (match.home_source or 'TBD')
            away = match.away_team.name if match.away_team else (match.away_source or 'TBD')
            record_tx(current_user, existing.amount or BET_AMOUNT, 'bet_removed',
                      f'Bet removed: {home} vs {away}')
            db.session.delete(existing)
            db.session.commit()
            flash(f'Bet removed. ${BET_AMOUNT:.2f} refunded to your balance.', 'info')
        return redirect(url_for('matches'))

    if prediction not in ('home', 'draw', 'away'):
        flash('Invalid prediction.', 'danger')
        return redirect(url_for('matches'))

    if prediction == 'draw' and match.is_knockout:
        flash('Draws are not allowed in knockout rounds.', 'warning')
        return redirect(url_for('matches'))

    home = match.home_team.name if match.home_team else (match.home_source or 'TBD')
    away = match.away_team.name if match.away_team else (match.away_source or 'TBD')

    existing = Bet.query.filter_by(user_id=current_user.id, match_id=match_id).first()
    if existing:
        # Changing pick: no extra charge
        existing.prediction = prediction
        existing.placed_at = datetime.now(timezone.utc)
        flash('Bet updated!', 'success')
    else:
        if current_user.balance < BET_AMOUNT:
            flash(f'Insufficient balance. You need ${BET_AMOUNT:.2f} to place a bet.', 'danger')
            return redirect(url_for('matches'))
        bet = Bet(user_id=current_user.id, match_id=match_id,
                  prediction=prediction, amount=BET_AMOUNT)
        db.session.add(bet)
        record_tx(current_user, -BET_AMOUNT, 'bet_placed',
                  f'Bet placed: {home} vs {away}')
        flash(f'Bet placed! ${BET_AMOUNT:.2f} deducted from your balance.', 'success')
    db.session.commit()
    return redirect(url_for('matches'))


@app.route('/tournament-bet', methods=['GET', 'POST'])
@login_required
def tournament_bet():
    from datetime import timedelta
    # Cutoff = 12 hours before first group stage match
    first_match = Match.query.filter_by(stage='Group Stage').order_by(Match.match_date).first()
    cutoff = None
    betting_open = True
    if first_match and first_match.match_date:
        cutoff = first_match.match_date.replace(tzinfo=timezone.utc) - timedelta(hours=12)
        betting_open = datetime.now(timezone.utc) < cutoff

    teams = Team.query.order_by(Team.group, Team.name).all()
    existing = current_user.tournament_bet

    if request.method == 'POST':
        if not betting_open:
            flash('Champion picks are closed.', 'danger')
            return redirect(url_for('tournament_bet'))
        team_id = request.form.get('team_id', type=int)
        team = db.session.get(Team, team_id)
        if not team:
            flash('Invalid team.', 'danger')
            return redirect(url_for('tournament_bet'))
        if existing:
            # Free change — already paid
            existing.team_id = team_id
            existing.placed_at = datetime.now(timezone.utc)
            flash(f'Champion pick updated to {team.name}!', 'success')
        else:
            if current_user.balance < TOURNAMENT_BET_AMOUNT:
                flash(f'Insufficient balance. You need ${TOURNAMENT_BET_AMOUNT:.0f} to place a champion pick.', 'danger')
                return redirect(url_for('tournament_bet'))
            tb = TournamentBet(user_id=current_user.id, team_id=team_id,
                               amount=TOURNAMENT_BET_AMOUNT)
            db.session.add(tb)
            record_tx(current_user, -TOURNAMENT_BET_AMOUNT, 'bet_placed',
                      f'Champion pick: {team.name} (${TOURNAMENT_BET_AMOUNT:.0f})')
            flash(f'Champion pick placed on {team.name}! ${TOURNAMENT_BET_AMOUNT:.0f} deducted.', 'success')
        db.session.commit()
        return redirect(url_for('dashboard'))

    return render_template('tournament_bet.html', teams=teams, existing=existing,
                           betting_open=betting_open, cutoff=cutoff,
                           amount=TOURNAMENT_BET_AMOUNT)


@app.route('/tournament-bet/remove', methods=['POST'])
@login_required
def tournament_bet_remove():
    from datetime import timedelta
    first_match = Match.query.filter_by(stage='Group Stage').order_by(Match.match_date).first()
    if first_match and first_match.match_date:
        cutoff = first_match.match_date.replace(tzinfo=timezone.utc) - timedelta(hours=12)
        if datetime.now(timezone.utc) >= cutoff:
            flash('Champion picks are closed — cannot remove.', 'danger')
            return redirect(url_for('tournament_bet'))
    existing = current_user.tournament_bet
    if existing:
        refund = existing.amount or TOURNAMENT_BET_AMOUNT
        team_name = existing.team.name
        db.session.delete(existing)
        record_tx(current_user, refund, 'bet_removed',
                  f'Champion pick removed: {team_name} — ${refund:.0f} refunded')
        db.session.commit()
        flash(f'Champion pick removed. ${refund:.0f} refunded to your balance.', 'info')
    return redirect(url_for('tournament_bet'))


@app.route('/bracket')
@login_required
def bracket_view():
    def slots(stage, slot_list):
        all_m = {m.bracket_slot: m for m in Match.query.filter_by(stage=stage).all()}
        return [all_m.get(s) for s in slot_list]

    b = {
        'r32_l':  slots('Round of 32',   ['R32-01','R32-02','R32-03','R32-04','R32-05','R32-06','R32-07','R32-08']),
        'r16_l':  slots('Round of 16',   ['R16-01','R16-02','R16-03','R16-04']),
        'qf_l':   slots('Quarter-Final', ['QF-01','QF-02']),
        'sf_l':   slots('Semi-Final',    ['SF-01']),
        'final':  Match.query.filter_by(bracket_slot='FINAL').first(),
        'sf_r':   slots('Semi-Final',    ['SF-02']),
        'qf_r':   slots('Quarter-Final', ['QF-03','QF-04']),
        'r16_r':  slots('Round of 16',   ['R16-05','R16-06','R16-07','R16-08']),
        'r32_r':  slots('Round of 32',   ['R32-09','R32-10','R32-11','R32-12','R32-13','R32-14','R32-15','R32-16']),
        'third':  Match.query.filter_by(bracket_slot='3RD').first(),
    }

    # Group standings
    teams = Team.query.all()
    stats = {t.id: {'team': t, 'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0, 'played': 0} for t in teams}
    for m in Match.query.filter_by(stage='Group Stage').all():
        if m.result is None:
            continue
        if m.home_team_id not in stats or m.away_team_id not in stats:
            continue
        h, a = stats[m.home_team_id], stats[m.away_team_id]
        hs, as_ = m.home_score or 0, m.away_score or 0
        h['gf'] += hs; h['ga'] += as_; h['gd'] = h['gf'] - h['ga']; h['played'] += 1
        a['gf'] += as_; a['ga'] += hs; a['gd'] = a['gf'] - a['ga']; a['played'] += 1
        if m.result == 'home':   h['pts'] += 3
        elif m.result == 'away': a['pts'] += 3
        else: h['pts'] += 1; a['pts'] += 1

    groups = {}
    for s in stats.values():
        g = s['team'].group
        if g:
            groups.setdefault(g, []).append(s)
    for g in groups:
        groups[g].sort(key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)
    groups = dict(sorted(groups.items()))

    return render_template('bracket.html', b=b, groups=groups)


@app.route('/leaderboard')
@login_required
def leaderboard():
    users = User.query.filter_by(is_admin=False).all()
    users.sort(key=lambda u: u.total_points(), reverse=True)
    return render_template('leaderboard.html', users=users)

# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_users = User.query.filter_by(is_admin=False).count()
    total_bets = Bet.query.count()
    pending_matches = Match.query.filter(Match.result.is_(None)).count()
    recent_bets = Bet.query.order_by(Bet.placed_at.desc()).limit(10).all()
    return render_template('admin/dashboard.html', total_users=total_users,
                           total_bets=total_bets, pending_matches=pending_matches,
                           recent_bets=recent_bets)


@app.route('/admin/matches')
@login_required
@admin_required
def admin_matches():
    all_matches = Match.query.order_by(Match.match_date).all()
    return render_template('admin/matches.html', matches=all_matches)


@app.route('/admin/matches/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_match():
    teams = Team.query.order_by(Team.name).all()
    if request.method == 'POST':
        home_id = request.form.get('home_team_id', type=int)
        away_id = request.form.get('away_team_id', type=int)
        date_str = request.form.get('match_date')
        stage = request.form.get('stage', 'Group Stage')
        venue = request.form.get('venue', '')
        try:
            match_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date format.', 'danger')
            return render_template('admin/add_match.html', teams=teams)
        if home_id == away_id:
            flash('Home and away teams must be different.', 'danger')
            return render_template('admin/add_match.html', teams=teams)
        match = Match(home_team_id=home_id, away_team_id=away_id,
                      match_date=match_date, stage=stage, venue=venue)
        db.session.add(match)
        db.session.commit()
        flash('Match added.', 'success')
        return redirect(url_for('admin_matches'))
    return render_template('admin/add_match.html', teams=teams)


@app.route('/admin/matches/<int:match_id>/result', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_set_result(match_id):
    match = db.session.get(Match, match_id)
    if not match:
        abort(404)
    if request.method == 'POST':
        home_score = request.form.get('home_score', type=int)
        away_score = request.form.get('away_score', type=int)
        if home_score is None or away_score is None:
            flash('Please enter both scores.', 'danger')
            return render_template('admin/set_result.html', match=match, show_ko_winner=False)

        if home_score > away_score:
            result = 'home'
        elif away_score > home_score:
            result = 'away'
        else:
            result = 'draw'

        # Knockout matches cannot end in a draw — admin selects ET/penalties winner
        if match.is_knockout and result == 'draw':
            ko_winner = request.form.get('ko_winner')
            if ko_winner not in ('home', 'away'):
                flash('Scores are level — select the winner (ET / penalties).', 'warning')
                return render_template('admin/set_result.html', match=match,
                                       show_ko_winner=True,
                                       home_score=home_score, away_score=away_score)
            result = ko_winner

        _apply_match_result(match, home_score, away_score, result)
        db.session.commit()

        # Advance bracket immediately after result is saved
        from bracket import advance_bracket
        advance_bracket()

        flash('Result saved and points awarded.', 'success')
        return redirect(url_for('admin_matches'))
    return render_template('admin/set_result.html', match=match,
                           show_ko_winner=False, home_score=None, away_score=None)


@app.route('/admin/matches/<int:match_id>/lock', methods=['POST'])
@login_required
@admin_required
def admin_lock_match(match_id):
    match = db.session.get(Match, match_id)
    if not match:
        abort(404)
    match.is_locked = True
    db.session.commit()
    flash('Match locked — no more bets accepted.', 'info')
    return redirect(url_for('admin_matches'))


@app.route('/admin/sync-scores', methods=['POST'])
@login_required
@admin_required
def admin_sync_scores():
    synced, skipped, errors = _do_espn_sync()
    for msg in errors:
        flash(msg, 'warning')
    flash(f'ESPN sync: {synced} result(s) saved, {skipped} skipped.', 'success')
    return redirect(url_for('admin_matches'))


@app.route('/admin/pool')
@login_required
@admin_required
def admin_pool():
    matches = Match.query.order_by(Match.match_date).all()
    return render_template('admin/pool.html', matches=matches)


@app.route('/admin/tournament-winner', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_tournament_winner():
    teams = Team.query.order_by(Team.name).all()
    if request.method == 'POST':
        team_id = request.form.get('team_id', type=int)
        TournamentBet.query.filter_by(team_id=team_id).update({'points': 10})
        TournamentBet.query.filter(TournamentBet.team_id != team_id).update({'points': 0})
        db.session.commit()
        flash('Tournament winner set and points awarded!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/tournament_winner.html', teams=teams)


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@app.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def admin_toggle_admin(user_id):
    user = db.session.get(User, user_id)
    if not user or user.id == current_user.id:
        abort(400)
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"{'Admin granted to' if user.is_admin else 'Admin removed from'} {user.username}.", 'info')
    return redirect(url_for('admin_users'))


@app.route('/balance')
@login_required
def balance():
    bets = (Bet.query
            .filter_by(user_id=current_user.id)
            .order_by(Bet.placed_at.desc())
            .all())
    transactions = (Transaction.query
                    .filter_by(user_id=current_user.id)
                    .order_by(Transaction.created_at.desc())
                    .all())
    total_wagered = sum(b.amount or BET_AMOUNT for b in bets)
    total_returned = sum(b.payout for b in bets if b.payout is not None)
    net = round(total_returned - total_wagered, 2)
    pending_payout = PayoutRequest.query.filter_by(
        user_id=current_user.id, status='pending'
    ).first()
    payout_history = (PayoutRequest.query
                      .filter_by(user_id=current_user.id)
                      .order_by(PayoutRequest.requested_at.desc())
                      .all())
    return render_template('balance.html', bets=bets, transactions=transactions,
                           total_wagered=total_wagered,
                           total_won=total_returned, net=net,
                           pending_payout=pending_payout,
                           payout_history=payout_history)


@app.route('/admin/users/<int:user_id>/add-credit', methods=['POST'])
@login_required
@admin_required
def admin_add_credit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    amount = request.form.get('amount', type=float)
    if amount is None or amount == 0:
        flash('Enter a non-zero amount.', 'danger')
        return redirect(url_for('admin_users'))
    if amount > 0:
        record_tx(user, amount, 'admin_credit',
                  f'Admin added ${amount:.2f} — by {current_user.username}')
        db.session.commit()
        flash(f'Added ${amount:.2f} to {user.username}\'s balance.', 'success')
    else:
        deduct = abs(amount)
        record_tx(user, -deduct, 'admin_debit',
                  f'Admin deducted ${deduct:.2f} — by {current_user.username}')
        db.session.commit()
        flash(f'Deducted ${deduct:.2f} from {user.username}\'s balance.', 'info')
    return redirect(url_for('admin_users'))


@app.route('/admin/teams')
@login_required
@admin_required
def admin_teams():
    teams = Team.query.order_by(Team.group, Team.name).all()
    return render_template('admin/teams.html', teams=teams)


@app.route('/admin/teams/<int:team_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_team(team_id):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    name = request.form.get('name', '').strip()
    flag = request.form.get('flag_emoji', '').strip()
    group = request.form.get('group', '').strip().upper()
    if name:
        team.name = name
    if flag:
        team.flag_emoji = flag
    if group:
        team.group = group
    db.session.commit()
    flash(f'Team updated: {team.flag_emoji} {team.name}', 'success')
    return redirect(url_for('admin_teams'))


@app.route('/payout/request', methods=['POST'])
@login_required
def payout_request():
    pending = PayoutRequest.query.filter_by(
        user_id=current_user.id, status='pending'
    ).first()
    if pending:
        flash('You already have a pending payout request.', 'warning')
        return redirect(url_for('balance'))
    if current_user.balance < 0.01:
        flash('No balance to request payout for.', 'warning')
        return redirect(url_for('balance'))
    amount = current_user.balance
    record_tx(current_user, -amount, 'payout_requested',
              f'Payout requested: ${amount:.2f}')
    pr = PayoutRequest(user_id=current_user.id, amount=amount)
    db.session.add(pr)
    db.session.commit()
    flash(f'Payout request submitted for ${amount:.2f}. Admin will send payment shortly.', 'success')
    return redirect(url_for('balance'))


@app.route('/admin/payouts')
@login_required
@admin_required
def admin_payouts():
    pending = PayoutRequest.query.filter_by(status='pending').order_by(PayoutRequest.requested_at).all()
    paid = PayoutRequest.query.filter_by(status='paid').order_by(PayoutRequest.paid_at.desc()).limit(50).all()
    return render_template('admin/payouts.html', pending=pending, paid=paid)


@app.route('/admin/payouts/<int:pr_id>/mark-paid', methods=['POST'])
@login_required
@admin_required
def admin_mark_payout_paid(pr_id):
    pr = db.session.get(PayoutRequest, pr_id)
    if not pr or pr.status == 'paid':
        abort(404)
    pr.status = 'paid'
    pr.paid_at = datetime.now(timezone.utc)
    db.session.commit()
    flash(f'Marked ${pr.amount:.2f} payout as paid for {pr.user.username}.', 'success')
    return redirect(url_for('admin_payouts'))



@app.route('/admin/recalculate-bracket', methods=['POST'])
@login_required
@admin_required
def admin_recalculate_bracket():
    from bracket import advance_bracket
    changed = advance_bracket()
    flash(f'Bracket recalculated. {"Teams advanced." if changed else "No changes."}', 'success')
    return redirect(url_for('admin_matches'))

# ---------------------------------------------------------------------------
# Scheduler — bracket auto-advance every hour
# ---------------------------------------------------------------------------

def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(daemon=True)

    def _advance_job():
        with app.app_context():
            from bracket import advance_bracket
            advance_bracket()

    def _espn_sync_job():
        with app.app_context():
            _do_espn_sync()  # errors are silently ignored in background

    scheduler.add_job(_advance_job,   'interval', hours=1,   id='bracket_hourly')
    scheduler.add_job(_espn_sync_job, 'interval', minutes=30, id='espn_sync')
    scheduler.start()
    return scheduler


# Guard: Flask debug mode spawns two processes via the reloader.
# WERKZEUG_RUN_MAIN is set only in the live worker child.
import os as _os
if _os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    _scheduler = _start_scheduler()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
