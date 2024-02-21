from flask import Flask, render_template, request, redirect, url_for, session
from sshtunnel import SSHTunnelForwarder
import psycopg2

app = Flask(__name__)
app.secret_key = 'aa26fdcb-5d80-4edd-9add-10ba4e94682f'

# SSH and Database connection settings
ssh_host = '194.149.135.130'
ssh_username = 't_auditly'
ssh_password = 'e3286703'
local_bind_port = 9999
remote_bind_address = ('localhost', 5432)
db_name = 'db_202324z_va_prj_auditly'
db_user = 'db_202324z_va_prj_auditly_owner'
db_password = 'ff51411fe971'

# Establish SSH tunnel and database connection
def get_db_connection():
    tunnel = SSHTunnelForwarder(
        (ssh_host, 22),
        ssh_username=ssh_username,
        ssh_password=ssh_password,
        remote_bind_address=remote_bind_address,
        local_bind_address=('localhost', local_bind_port)
    )
    tunnel.start()
    conn = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_password,
        host='localhost',
        port=tunnel.local_bind_port
    )
    return conn, tunnel

@app.route('/')
def index():
    return "Auditly Home Page"

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form['firstName']
        last_name = request.form['lastName']
        email = request.form['email']
        domain_names = request.form['domainNames'].split(',')  # Split the input into a list

        conn, tunnel = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT MAX(Id) FROM AuditlyUser;")
        max_id_result = cur.fetchone()
        user_id = (max_id_result[0] or 0) + 1
        # Insert the new user into AuditlyUser and get the generated ID
        cur.execute("""
            INSERT INTO AuditlyUser (Id, FirstName, LastName, EmailAddress)
            VALUES (%s, %s, %s, %s);
        """, (user_id, first_name, last_name, email))

        # Insert domain names into Product table
        for domain_name in domain_names:
            domain_name = domain_name.strip()  # Remove any leading/trailing whitespace
            # Avoid inserting duplicate domain names
            cur.execute("""
                INSERT INTO Product (DomainName)
                VALUES (%s) ON CONFLICT (DomainName) DO NOTHING;
            """, (domain_name,))

            # Link domain names with the user in UserProduct table or similar
            cur.execute("""
                INSERT INTO UserProduct (UserId, DomainName)
                VALUES (%s, %s);
            """, (user_id, domain_name))

        conn.commit()
        cur.close()
        conn.close()
        tunnel.stop()

        return redirect(url_for('login'))
    else:
        return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']

        # Connect to the database
        conn, tunnel = get_db_connection()
        cur = conn.cursor()

        # Check if the email exists in the AuditlyUser table
        query = "SELECT * FROM AuditlyUser WHERE EmailAddress = %s"
        cur.execute(query, (email,))
        user = cur.fetchone()

        cur.close()
        conn.close()
        tunnel.stop()

        if user:
            # Email found, store it in session and redirect to reviews page
            session['user_email'] = email
            return redirect(url_for('reviews'))
        else:
            # Email not found, show an error or redirect back to login with an error
            return "Email not found. Please register.", 401
    else:
        # Show the login form
        return render_template('login.html')


@app.route('/reviews')
def reviews():
    # First, check if there's an email in the session for the current session
    if 'user_email' not in session:
        return redirect(url_for('login'))

    email = session['user_email']
    
    conn, tunnel = get_db_connection()
    cur = conn.cursor()

    # Constructing the base SQL query
    sql_query = """
    SELECT r.ReviewText, r.ReviewerScore, r.Sentiment, r.DateOfReview, p.DomainName, rv.FirstName, rv.LastName, r.Id
    FROM Review r
    JOIN Reviewer rv ON r.ReviewerId = rv.Id
    JOIN Product p ON r.ProductDomainName = p.DomainName
    JOIN UserProduct up ON p.DomainName = up.DomainName
    JOIN AuditlyUser au ON up.UserId = au.Id
    WHERE au.EmailAddress = %s
    """
    
    # Collecting filter parameters
    sql_params = [email]
    review_score = request.args.get('review_score')
    score_filter_option = request.args.get('score_filter_option', 'equal')  # Fetch the score filter option with a default
    date_of_review = request.args.get('date_of_review')
    date_filter_option = request.args.get('date_filter_option', 'equal')  # Same for the date filter option
    review_sentiment = request.args.get('review_sentiment')
    product_domain_name = request.args.get('product_domain_name')
    
    # Filter conditions
    if review_score:
        # Logic to decide the SQL symbol based on the filter option
        review_score_comparator = '=' if score_filter_option == 'equal' else '>' if score_filter_option == 'greater' else '<'
        sql_query += f" AND r.ReviewerScore {review_score_comparator} %s"
        sql_params.append(review_score)
    if review_sentiment:
        sql_query += " AND r.Sentiment = %s"
        sql_params.append(review_sentiment)
    if date_of_review:
        # Logic to adjust the SQL where clause for the review date
        date_review_comparator = '=' if date_filter_option == 'equal' else '>' if date_filter_option == 'greater' else '<'
        sql_query += f" AND r.DateOfReview {date_review_comparator} %s"
        sql_params.append(date_of_review)
    if product_domain_name:
        sql_query += " AND p.DomainName = %s"
        sql_params.append(product_domain_name)
    
    # Execute query with filters
    cur.execute(sql_query, sql_params)
    reviews = cur.fetchall()
    
    reviewer_ids = [review[-1] for review in reviews]  # Assuming last element is the reviewer_id
    session['reviewer_ids'] = reviewer_ids

    cur.close()
    conn.close()
    tunnel.stop()
    
    # Now, pass the reviews and the potential query params to your template
    return render_template('reviews.html', reviews=reviews, form_data=request.args)

@app.route('/reviewer/<int:reviewer_id>')
def reviewer_info(reviewer_id):
    conn, tunnel = get_db_connection()
    cur = conn.cursor()

    # Fetch additional information about the reviewer
    cur.execute("""
        SELECT FirstName, LastName, Position, CompanyName, EmailAddress, LinkedInUserProfileUrl
        FROM Reviewer
        WHERE Id = %s;
    """, (reviewer_id,))
    reviewer_info = cur.fetchone()

    cur.close()
    conn.close()
    tunnel.stop()

    if reviewer_info:
        # Pass the reviewer information to the template
        return render_template('reviewer_info.html', reviewer_info=reviewer_info)
    else:
        return "Reviewer not found", 404

@app.route('/campaign', methods=['GET'])
def campaign():
    if 'reviewer_ids' not in session:
        # Redirect if there's no campaign to start (no reviewer IDs stored)
        return redirect(url_for('reviews'))
    
    return render_template('campaign.html')

@app.route('/start-campaign', methods=['POST'])
def start_campaign():
    if 'reviewer_ids' not in session or not session['reviewer_ids']:
        return "No campaign to start", 400

    email_subject = request.form['emailSubject']
    email_message = request.form['emailMessage']
    linkedin_message = request.form['linkedinMessage']
    reviewer_ids = session.pop('reviewer_ids')  # Get and clear reviewer IDs from session
    
    conn, tunnel = get_db_connection()
    cur = conn.cursor()

    if 'user_email' not in session:
        return "User identification failed", 403
    
    user_email = session['user_email']
        # Fetch the user_id based on the email stored in the session
    cur.execute("SELECT Id FROM AuditlyUser WHERE EmailAddress = %s", (user_email,))
    user_id_result = cur.fetchone()
    if not user_id_result:
        cur.close()
        conn.close()
        tunnel.stop()
        return "User not found", 404

    user_id = user_id_result[0]

    cur.execute("SELECT MAX(Id) FROM Message;")
    max_id_result = cur.fetchone()
    message_id = (max_id_result[0] or 0) + 1

    num_reviewers = 0
    for reviewer_id in reviewer_ids:
        # Insert into the Message table. Assuming id is auto-incremented.
        cur.execute("""
            INSERT INTO Message (id, userid, reviewerid, emailsubject, emailtext, linkedIntext)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (message_id, user_id, reviewer_id, email_subject, email_message, linkedin_message))
        num_reviewers += 1
        message_id += 1

    conn.commit()

    cur.close()
    conn.close()
    tunnel.stop()

    # Placeholder for where you'd insert into the 'Message' table or send messages
    
    return f"Congratulations, you have started a message campaign using {num_reviewers} people."

if __name__ == '__main__':
    app.run(debug=True)
