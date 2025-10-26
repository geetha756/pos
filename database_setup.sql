-- ============================================
-- Sip & Snack Portal Database Setup Script
-- ============================================
-- This script sets up the database schema, user, and all necessary tables
-- for the Restaurant Chain Management Portal.
--
-- PREREQUISITE: Create the database manually first, then run this script.
--
-- Run this script as a PostgreSQL superuser (usually 'postgres')
-- ============================================

-- ============================================
-- 1. SETUP USER AND CONNECT TO DATABASE
-- ============================================

-- Create application user (with validation)
DO $$
BEGIN
    -- Create user only if it doesn't exist
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sipnsnack_user') THEN
        CREATE USER sipnsnack_user WITH PASSWORD 's!pnsn@ck';
    END IF;
END
$$;

-- Grant privileges on the existing database
-- (Run this script while connected to the sipnsnack database)
GRANT ALL PRIVILEGES ON DATABASE sipnsnack TO sipnsnack_user;

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sipnsnack_user;

-- ============================================
-- 2. CREATE TABLES
-- ============================================

-- Enable UUID extension (required for UUID columns)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create locations table
CREATE TABLE IF NOT EXISTS locations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    phone VARCHAR(20),
    email VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create master_menu table
CREATE TABLE IF NOT EXISTS master_menu (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    category VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    image_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create location_menu table (junction table for location-specific menu items)
CREATE TABLE IF NOT EXISTS location_menu (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id) ON DELETE CASCADE,
    master_menu_id UUID REFERENCES master_menu(id) ON DELETE CASCADE,
    price DECIMAL(10,2), -- Location can override price
    is_available BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, master_menu_id)
);

-- Create orders table
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id),
    order_number VARCHAR(50) UNIQUE NOT NULL,
    customer_name VARCHAR(255),
    customer_phone VARCHAR(20),
    customer_email VARCHAR(255),
    order_type VARCHAR(50), -- dine-in, takeaway, delivery
    status VARCHAR(50) DEFAULT 'pending', -- pending, preparing, ready, completed, cancelled
    total_amount DECIMAL(10,2) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create order_items table
CREATE TABLE IF NOT EXISTS order_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
    location_menu_id UUID REFERENCES location_menu(id),
    master_menu_id UUID REFERENCES master_menu(id), -- For historical reference
    item_name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    total_price DECIMAL(10,2) NOT NULL,
    notes TEXT
);

-- Create user_sessions table (for authentication logging)
CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    user_name VARCHAR(255),
    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    logout_time TIMESTAMP,
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

-- Create departments table
CREATE TABLE IF NOT EXISTS departments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    manager_id UUID REFERENCES staff(id),
    budget DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create positions table
CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    department_id UUID REFERENCES departments(id),
    salary_min DECIMAL(10,2),
    salary_max DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Drop and recreate staff table to handle schema changes
DROP TABLE IF EXISTS staff CASCADE;

-- Create staff table with new structure
CREATE TABLE staff (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    employee_id VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(20),
    position_id UUID REFERENCES positions(id),
    department_id UUID REFERENCES departments(id),
    location_id UUID REFERENCES locations(id),
    hire_date DATE NOT NULL,
    salary DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE,
    manager_id UUID REFERENCES staff(id),
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    emergency_contact_name VARCHAR(255),
    emergency_contact_phone VARCHAR(20),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 3. ADD UNIQUE CONSTRAINTS
-- ============================================

-- Add unique constraints for location and menu names (with error handling)
DO $$
BEGIN
    -- Add unique constraint to locations table if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'locations_name_key'
        AND table_name = 'locations'
    ) THEN
        ALTER TABLE locations ADD CONSTRAINT locations_name_key UNIQUE (name);
    END IF;

    -- Add unique constraint to master_menu table if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'master_menu_name_key'
        AND table_name = 'master_menu'
    ) THEN
        ALTER TABLE master_menu ADD CONSTRAINT master_menu_name_key UNIQUE (name);
    END IF;
EXCEPTION
    WHEN others THEN
        RAISE NOTICE 'Could not add unique constraints. Please ensure no duplicate names exist in locations or master_menu tables.';
END $$;

-- ============================================
-- 4. CREATE INDEXES FOR PERFORMANCE
-- ============================================

-- Indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_master_menu_category ON master_menu(category);
CREATE INDEX IF NOT EXISTS idx_master_menu_active ON master_menu(is_active);
CREATE INDEX IF NOT EXISTS idx_location_menu_location ON location_menu(location_id);
CREATE INDEX IF NOT EXISTS idx_location_menu_menu ON location_menu(master_menu_id);
CREATE INDEX IF NOT EXISTS idx_orders_location ON orders(location_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_email ON user_sessions(user_email);
CREATE INDEX IF NOT EXISTS idx_user_sessions_active ON user_sessions(is_active);

-- Indexes for departments table
CREATE INDEX IF NOT EXISTS idx_departments_name ON departments(name);
CREATE INDEX IF NOT EXISTS idx_departments_manager ON departments(manager_id);
CREATE INDEX IF NOT EXISTS idx_departments_active ON departments(is_active);

-- Indexes for positions table
CREATE INDEX IF NOT EXISTS idx_positions_title ON positions(title);
CREATE INDEX IF NOT EXISTS idx_positions_department ON positions(department_id);
CREATE INDEX IF NOT EXISTS idx_positions_active ON positions(is_active);

-- Indexes for staff table
CREATE INDEX IF NOT EXISTS idx_staff_employee_id ON staff(employee_id);
CREATE INDEX IF NOT EXISTS idx_staff_email ON staff(email);
CREATE INDEX IF NOT EXISTS idx_staff_position_id ON staff(position_id);
CREATE INDEX IF NOT EXISTS idx_staff_department_id ON staff(department_id);
CREATE INDEX IF NOT EXISTS idx_staff_location ON staff(location_id);
CREATE INDEX IF NOT EXISTS idx_staff_manager ON staff(manager_id);
CREATE INDEX IF NOT EXISTS idx_staff_active ON staff(is_active);
CREATE INDEX IF NOT EXISTS idx_staff_hire_date ON staff(hire_date);

-- ============================================
-- 5. SAMPLE DATA (OPTIONAL)
-- ============================================

-- Insert sample locations (IDs will be auto-generated as UUIDs)
INSERT INTO locations (name, address, city, state, zip_code, phone, email) VALUES
('Downtown Branch', '123 Main St', 'New York', 'NY', '10001', '+1-555-0101', 'downtown@sipnsnack.com'),
('Mall Location', '456 Shopping Plaza', 'Los Angeles', 'CA', '90210', '+1-555-0102', 'mall@sipnsnack.com'),
('Airport Terminal', '789 Terminal Rd', 'Chicago', 'IL', '60601', '+1-555-0103', 'airport@sipnsnack.com')
ON CONFLICT DO NOTHING;

-- Insert sample master menu items (IDs will be auto-generated as UUIDs)
INSERT INTO master_menu (name, description, price, category, is_active) VALUES
('Classic Coffee', 'Freshly brewed coffee', 3.50, 'Beverages', true),
('Cappuccino', 'Espresso with steamed milk foam', 4.25, 'Beverages', true),
('Green Tea', 'Organic green tea', 2.75, 'Beverages', true),
('Grilled Cheese Sandwich', 'Melted cheese on toasted bread', 6.99, 'Main Course', true),
('Caesar Salad', 'Crisp romaine lettuce with caesar dressing', 8.50, 'Salads', true),
('Chocolate Brownie', 'Rich chocolate brownie with vanilla ice cream', 5.25, 'Desserts', true),
('French Fries', 'Crispy golden fries', 4.50, 'Snacks', true),
('Ice Cream Sundae', 'Vanilla ice cream with chocolate sauce', 4.99, 'Desserts', true)
ON CONFLICT DO NOTHING;

-- Insert sample departments
INSERT INTO departments (name, description, budget, is_active) VALUES
('Management', 'Executive and managerial staff overseeing operations', 150000.00, true),
('Operations', 'Front-line staff handling customer service and operations', 200000.00, true),
('Kitchen', 'Food preparation and kitchen operations', 100000.00, true),
('Customer Service', 'Customer support and service staff', 80000.00, true),
('HR', 'Human resources and personnel management', 60000.00, true),
('Finance', 'Financial operations and accounting', 70000.00, true),
('IT', 'Information technology and systems support', 90000.00, true)
ON CONFLICT DO NOTHING;

-- Insert sample positions
INSERT INTO positions (title, description, department_id, salary_min, salary_max, is_active) VALUES
('Store Manager', 'Overall management of store operations', (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), 45000.00, 65000.00, true),
('Assistant Manager', 'Assistant to store manager', (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), 35000.00, 50000.00, true),
('Barista', 'Coffee and beverage preparation', (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), 25000.00, 35000.00, true),
('Cashier', 'Customer checkout and payment processing', (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), 22000.00, 30000.00, true),
('Kitchen Staff', 'Food preparation and kitchen operations', (SELECT id FROM departments WHERE name = 'Kitchen' LIMIT 1), 25000.00, 35000.00, true),
('Customer Service Rep', 'Customer support and assistance', (SELECT id FROM departments WHERE name = 'Customer Service' LIMIT 1), 28000.00, 38000.00, true),
('HR Manager', 'Human resources management', (SELECT id FROM departments WHERE name = 'HR' LIMIT 1), 40000.00, 55000.00, true),
('Finance Manager', 'Financial operations management', (SELECT id FROM departments WHERE name = 'Finance' LIMIT 1), 42000.00, 58000.00, true),
('IT Support', 'Technical support and systems maintenance', (SELECT id FROM departments WHERE name = 'IT' LIMIT 1), 35000.00, 50000.00, true)
ON CONFLICT DO NOTHING;

-- Insert sample staff (IDs will be auto-generated as UUIDs)
INSERT INTO staff (employee_id, first_name, last_name, email, phone, position_id, department_id, location_id, hire_date, salary, is_active, address, city, state, zip_code, emergency_contact_name, emergency_contact_phone) VALUES
('EMP001', 'John', 'Smith', 'john.smith@sipnsnack.com', '+1-555-1001', (SELECT id FROM positions WHERE title = 'Store Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-01-15', 55000.00, true, '123 Oak St', 'New York', 'NY', '10001', 'Jane Smith', '+1-555-2001'),
('EMP002', 'Sarah', 'Johnson', 'sarah.johnson@sipnsnack.com', '+1-555-1002', (SELECT id FROM positions WHERE title = 'Assistant Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-03-01', 45000.00, true, '456 Maple Ave', 'New York', 'NY', '10002', 'Mike Johnson', '+1-555-2002'),
('EMP003', 'Mike', 'Davis', 'mike.davis@sipnsnack.com', '+1-555-1003', (SELECT id FROM positions WHERE title = 'Barista' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-02-15', 32000.00, true, '789 Pine St', 'New York', 'NY', '10003', 'Lisa Davis', '+1-555-2003'),
('EMP004', 'Emily', 'Wilson', 'emily.wilson@sipnsnack.com', '+1-555-1004', (SELECT id FROM positions WHERE title = 'Cashier' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-04-01', 28000.00, true, '321 Elm St', 'New York', 'NY', '10004', 'David Wilson', '+1-555-2004'),
('EMP005', 'Robert', 'Brown', 'robert.brown@sipnsnack.com', '+1-555-1005', (SELECT id FROM positions WHERE title = 'Store Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-01-20', 55000.00, true, '654 Cedar Ave', 'Los Angeles', 'CA', '90210', 'Maria Brown', '+1-555-2005'),
('EMP006', 'Lisa', 'Garcia', 'lisa.garcia@sipnsnack.com', '+1-555-1006', (SELECT id FROM positions WHERE title = 'Kitchen Staff' LIMIT 1), (SELECT id FROM departments WHERE name = 'Kitchen' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-03-15', 30000.00, true, '987 Birch Blvd', 'Los Angeles', 'CA', '90211', 'Carlos Garcia', '+1-555-2006'),
('EMP007', 'David', 'Miller', 'david.miller@sipnsnack.com', '+1-555-1007', (SELECT id FROM positions WHERE title = 'Barista' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-05-01', 32000.00, true, '147 Walnut St', 'Los Angeles', 'CA', '90212', 'Anna Miller', '+1-555-2007'),
('EMP008', 'Jennifer', 'Martinez', 'jennifer.martinez@sipnsnack.com', '+1-555-1008', (SELECT id FROM positions WHERE title = 'Assistant Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), '2023-02-01', 45000.00, true, '258 Spruce Ln', 'Chicago', 'IL', '60601', 'Luis Martinez', '+1-555-2008')
ON CONFLICT DO NOTHING;

-- Update manager references (do this after initial insert)
UPDATE staff SET manager_id = (SELECT id FROM staff WHERE employee_id = 'EMP001') WHERE employee_id IN ('EMP002', 'EMP003', 'EMP004') AND manager_id IS NULL;
UPDATE staff SET manager_id = (SELECT id FROM staff WHERE employee_id = 'EMP005') WHERE employee_id IN ('EMP006', 'EMP007') AND manager_id IS NULL;
UPDATE staff SET manager_id = (SELECT id FROM staff WHERE employee_id = 'EMP008') WHERE employee_id = 'EMP008' AND manager_id IS NULL;

-- Update department managers
UPDATE departments SET manager_id = (SELECT id FROM staff WHERE employee_id = 'EMP001') WHERE name = 'Management' AND manager_id IS NULL;

-- ============================================
-- 6. GRANT PERMISSIONS TO APPLICATION USER
-- ============================================

-- Grant all privileges on existing tables
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sipnsnack_user;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sipnsnack_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO sipnsnack_user;

-- ============================================
-- SETUP COMPLETE
-- ============================================
-- Database: sipnsnack
-- User: sipnsnack_user
-- Tables created: 9
-- Unique constraints added
-- Sample data inserted
--
-- Next steps:
-- 1. Update your .env file with database credentials
-- 2. Run: python app.py
-- 3. Visit: http://localhost:5000
-- ============================================

-- Display completion message
DO $$
BEGIN
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Sip & Snack Portal Database Setup Complete!';
    RAISE NOTICE '================================================';
END $$;
