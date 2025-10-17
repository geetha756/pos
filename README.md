# Restaurant Chain Management Portal

A comprehensive management portal for restaurant chains with multiple locations, built with Flask, PostgreSQL, and Bootstrap.

## Features

- **Master Menu Management**: Central configuration of menu items with categories and pricing
- **Location Menu Management**: Assign master menu items to specific locations with custom pricing
- **Order Management**: View and manage orders from all franchise locations with status tracking
- **Dashboard Interface**: Modern Bootstrap-based admin dashboard with responsive design
- **Real-time Statistics**: Live dashboard with order counts, revenue, and location metrics

## Technology Stack

- **Backend**: Python Flask with Blueprint architecture
- **Database**: PostgreSQL (no ORM - direct SQL queries)
- **Frontend**: Bootstrap 5 Dashboard Template
- **Static Assets**: All CSS/JS downloaded and stored locally (no CDN dependencies)

## Prerequisites

- Python 3.8+
- PostgreSQL 12+

## Configuration Files

The repository includes configuration and setup files:

- `dev.env` - Environment variables for development
- `database_setup.sql` - Complete database schema with sample data
- `database_setup_minimal.sql` - Minimal database schema (tables only)
- `requirements.txt` - Python dependencies

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Database Setup

**Step 1: Create the database manually**
```sql
-- Connect to PostgreSQL as superuser and run:
CREATE DATABASE sipnsnack;
```

**Step 2: Run the SQL setup script**

Choose one of the SQL scripts in the project root:

**Option A: Complete Setup (with sample data)**
```bash
# First, create and connect to the database
psql -U postgres -c "CREATE DATABASE sipnsnack;"
psql -U postgres -d sipnsnack -f database_setup.sql
```

**Option B: Minimal Setup (tables only)**
```bash
# First, create and connect to the database
psql -U postgres -c "CREATE DATABASE sipnsnack;"
psql -U postgres -d sipnsnack -f database_setup_minimal.sql
```

**Manual Alternative:**
If you prefer to do everything manually, create the user and run all table creation statements from the scripts above.

### 3. Environment Configuration

The `dev.env` file contains the development configuration. Edit it with your database connection:

```env
# Flask Configuration
SECRET_KEY=dev-secret-key-change-in-production
FLASK_ENV=development

# Database Configuration
DATABASE_URL=postgresql://sipnsnack_user:s%21pnsn%40ck@localhost:5432/sipnsnack

# Security Settings
SESSION_COOKIE_SECURE=False
```

**Note:** For production, create a `.env` file or set environment variables directly.

### 4. Launch Application

```bash
python app.py
```

### 5. Access the Portal

Open your browser and navigate to `http://localhost:5000`

## Database Schema

The application uses the following main tables (all with UUID primary keys):

**Note:** All ID fields use UUID v4 format for global uniqueness and security.

- **`locations`** - Restaurant locations with contact information
  - `id` (UUID) - Primary key with auto-generated UUID
  - `name, address, city, state, zip_code, phone, email` - Location details
  - `created_at` - Timestamp

- **`master_menu`** - Central menu items with categories and base pricing
  - `id` (UUID) - Primary key with auto-generated UUID
  - `name, description, price, category, is_active` - Menu item details
  - `image_url, created_at, updated_at` - Additional metadata

- **`location_menu`** - Junction table for location-specific menu items and pricing
  - `id` (UUID) - Primary key with auto-generated UUID
  - `location_id, master_menu_id` (UUID) - Foreign keys
  - `price, is_available` - Location-specific overrides
  - `created_at` - Timestamp

- **`orders`** - Order records from all locations with customer details
  - `id` (UUID) - Primary key with auto-generated UUID
  - `location_id` (UUID) - Foreign key to locations
  - `order_number, customer_name, customer_phone, customer_email` - Order details
  - `order_type, status, total_amount, notes` - Order metadata
  - `created_at, updated_at` - Timestamps

- **`order_items`** - Individual items within orders
  - `id` (UUID) - Primary key with auto-generated UUID
  - `order_id, location_menu_id, master_menu_id` (UUID) - Foreign keys
  - `item_name, quantity, unit_price, total_price` - Item details
  - `notes` - Additional notes

## Usage Guide

### Getting Started

1. **Set up Database**: Run the SQL scripts to create database and tables
2. **Add Locations**: Create restaurant locations with contact information
3. **Create Master Menu**: Add menu items to the central catalog
4. **Assign Menu Items**: Configure which items are available at each location
5. **Monitor Orders**: View and manage orders from all locations

### Navigation

- **Dashboard**: Overview with key metrics and quick actions
- **Master Menu**: Manage central menu catalog
- **Locations**: Add and manage restaurant locations
- **Location Menu**: Assign menu items to specific locations
- **Orders**: View and manage all orders with filtering

## API Endpoints

The application provides RESTful endpoints:

- `GET /` - Dashboard
- `GET /master-menu` - Master menu management
- `GET /locations` - Location management
- `GET /location-menu` - Location menu assignment
- `GET /orders` - Order management

## Development

To run in development mode:

```bash
export FLASK_ENV=development
python app.py
```

## Production Deployment

For production deployment:

1. Set `SECRET_KEY` to a secure random value
2. Configure PostgreSQL connection with proper credentials
3. Set `FLASK_ENV=production`
4. Use a WSGI server like Gunicorn
5. Configure reverse proxy (nginx recommended)

## Troubleshooting

If you encounter issues with `psycopg2-binary` installation on Windows:

1. **Use Python 3.9-3.11** instead of Python 3.13
2. **Install PostgreSQL** and ensure development tools are available
3. **Use alternative libraries** like `psycopg` instead of `psycopg2-binary`

## License

This project is licensed under the MIT License.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Support

For support and questions, please open an issue on the GitHub repository.
