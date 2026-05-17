# StudyCollabz - Agile Study Group & Peer Matcher

StudyCollabz is a responsive, modern Flask-based web application designed to connect university students, facilitate academic collaboration, and coordinate study sessions.
### Purpose
Many students entering university often feel isolated and struggle to build meaningful academic connections. To address this, we developed StudyCollabz: a platform designed to help students find compatible study partners, using matching academic criteria. The platform aims to support students’ academic progress while also giving them opportunities to connect with the broader university community.
### Design
- **Backend (Flask)**: Handles page routing (like going to `/register` or `/dashboard`), user log-ins, and dynamically creates the HTML pages using the Jinja2 engine.
- **Database (Flask-SQLAlchemy & SQLite)**: A single database file securely stores user accounts, profiles, and friendship data. 
- **Styling (Modular CSS)**: Organized custom CSS files. Instead of heavy libraries, we use clean, page-specific stylesheets to ensure the web app loads quickly and looks modern.
- **Interactions (JavaScript)**: Handles dynamic actions on the screen, like showing the calendar grid and checking forms.

### How to Use

1. **Onboarding & Profiling**: When users sign up, they complete a quick profile specifying their degree, major, and minor fields.
2. **Interactive Dashboard**: The homepage displays academic matching suggestions, summary statistics of the user's network, and integrated calendar widgets.
3. **Discover & Search**: Users browse the **People** hub to search for fellow classmates, view detailed profiles, and send or accept friend requests.
4. **Coordination**: Users can view matched study partners and arrange collective schedules directly from their profile interfaces.

  

---

##  2. Group Members

| UWA ID  | Name            | GitHub Username |
|---------|-----------------|-----------------|
| 23284373| Mineth Perera   | ethnimp         |
| 24342886| Sarah Siddiqui  | onioncodes      |
| 24463471| Robert Ho       | OCEsLastHope    |
| 24230704| Laila Amin      | lailaaamin70    |
---
## 3. How to Launch the Application

### Installation & Run Steps

1. **Clone the repository**:

   ```bash

   git clone https://github.com/OCEsLastHope/cits3403.git

   cd cits3403

   ```

  
2. **Create and activate a virtual environment**:

   ```bash

   # Create environment

   python -m venv venv

  

   # Activate environment (Windows PowerShell)

   .\venv\Scripts\activate

  

   # Activate environment (Mac / Linux)

   source venv/bin/activate

   ```


3. **Install all required dependencies**:

   ```bash

   pip install -r requirements.txt

   ```


4. **Initialize and upgrade the database**:

   ```bash

   flask db upgrade

   ```


5. **Start the local development server**:

   ```bash

   flask run

   ```

   *The application will boot up in development mode and will be active at `http://127.0.0.1:5000`.*

  

---
## 4. How to Run the Tests

### A. Run Unit Tests (In-Memory Testing)

Unit tests validate the backend routing, database models, and authentication logic in isolation using in-memory SQLite mocks. Run them with:

```bash

python -m unittest discover tests "*_unit.py"

```

### B. Run Selenium UI Tests (Real-Browser Testing)

The UI tests verify form logic, client-side validation, page loading, and end-to-end user navigation flows by automating a real Google Chrome browser.

  

To run the Selenium tests:

```bash

python -m unittest tests/test_auth_selenium.py

```

## Disclaimer:

The **Forgot Password** (password reset) feature requires connection to an SMTP mail server to send live reset links. 

If you test the password reset feature without configuring these variables, it will result in an SMTP authentication/connection error.

To enable this feature, create a `.env` file in the root directory and add:
```env
# Required for password reset emails
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_google_app_password

# Required for signing reset tokens securely
SECRET_KEY=some_strong_secret_key
```

*Notes:*
* **Google App Password**: If using Gmail, `MAIL_PASSWORD` must be a **Google App Password** (not your regular account password) for SMTP authentication to succeed.
* **Fallback**: The rest of the application (login, registration, profiles, matching, and all automated/selenium tests) will function **100% perfectly** without these variables set. tests) will function **100% perfectly** without these variables set.