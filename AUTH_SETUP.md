# Google OAuth Authentication Setup

This document explains how to set up Google OAuth authentication for the Sip & Snack Portal.

## Prerequisites

1. A Google Cloud Console account
2. Python 3.7+ installed
3. PostgreSQL database set up

## Google OAuth Setup

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google+ API (or Google Identity API)

### 2. Configure OAuth Consent Screen

1. In the Google Cloud Console, go to "APIs & Services" > "OAuth consent screen"
2. Choose "Internal" user type (for SN15 organization only)
3. Fill in the required fields:
   - App name: "Sip & Snack Portal"
   - User support email: your SN15 email
   - Developer contact information: your SN15 email
4. Save and continue through the scopes section
5. **Important**: This restricts access to SN15 organization members only

### 3. Create OAuth Credentials

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "OAuth client ID"
3. Choose "Web application"
4. Add authorized redirect URIs:
   - For development: `http://localhost:5000/auth/callback`
   - For production: `https://yourdomain.com/auth/callback`
5. Save the credentials and note down:
   - Client ID
   - Client Secret

## Environment Configuration

### 1. Copy Environment File

```bash
cp dev.env.example dev.env
```

### 2. Update Environment Variables

Edit `dev.env` with your actual values:

```env
# Flask Configuration
SECRET_KEY=your-very-secure-secret-key-here
FLASK_ENV=development

# Database Configuration
DATABASE_URL=postgresql://user:password@localhost/sipnsnack

# Google OAuth Configuration
GOOGLE_CLIENT_ID=992597649559-l6e8rdc3aq5dvcq5gq6iu8klvre9vfd1.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-actual-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:5000/auth/callback

# Security Settings
SESSION_COOKIE_SECURE=False
```

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Database Setup

Make sure your PostgreSQL database is running and create the database:

```sql
CREATE DATABASE sipnsnack;
```

Then run the database setup script:

```bash
python -c "from database import init_db; init_db()"
```

### 3. Run the Application

```bash
python app.py
```

## Usage

1. Navigate to `http://localhost:5000`
2. You'll be redirected to the login page
3. Click "Sign in with Google"
4. Complete the Google OAuth flow
5. You'll be redirected back to the dashboard

## Features

- **Secure Authentication**: Google OAuth 2.0 with ID token verification
- **Organization Restriction**: Only SN15 organization members can access the portal
- **Email Validation**: Automatic validation of @sn15.com and @sn15.org email addresses
- **Session Management**: Secure session handling with user information
- **Protected Routes**: All application routes require authentication
- **User Profile**: Display user name and profile picture in the header
- **Logout Functionality**: Secure logout with session clearing
- **Access Control**: Clear error messages for unauthorized users

## Security Notes

- The application uses secure session cookies
- All routes are protected with the `@login_required` decorator
- User sessions are properly managed and cleared on logout
- Google ID tokens are verified for authenticity

## Troubleshooting

### Common Issues

1. **"Google OAuth not configured" error**
   - Make sure `GOOGLE_CLIENT_ID` is set in your environment file

2. **"Invalid token" error**
   - Check that your Google Client ID and Secret are correct
   - Ensure the redirect URI matches exactly

3. **Redirect URI mismatch**
   - Make sure the redirect URI in Google Console matches your environment variable

4. **Database connection issues**
   - Verify your `DATABASE_URL` is correct
   - Ensure PostgreSQL is running

### Development vs Production

For production deployment:

1. Set `FLASK_ENV=production`
2. Use a secure `SECRET_KEY`
3. Set `SESSION_COOKIE_SECURE=True`
4. Use HTTPS for your redirect URI
5. Update the redirect URI in Google Console to your production domain

## File Structure

```
routes/
├── auth.py              # Authentication routes and decorators
├── main.py              # Main dashboard (protected)
├── master_menu.py       # Menu management (protected)
├── locations.py         # Location management (protected)
├── location_menu.py    # Location-specific menus (protected)
└── orders.py           # Order management (protected)

templates/
├── auth/
│   └── login.html       # Beautiful login page with Google Sign-In
└── base.html           # Updated with user profile dropdown
```

## Next Steps

After setting up authentication, you can:

1. Customize the login page design
2. Add role-based access control
3. Implement user management features
4. Add audit logging for user actions
5. Set up email notifications for authentication events
