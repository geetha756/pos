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
('Downtown Branch', '123 Main St', 'New York', 'NY', '10001', '+1-555-0101', 'downtown@sn15.com'),
('Mall Location', '456 Shopping Plaza', 'Los Angeles', 'CA', '90210', '+1-555-0102', 'mall@sn15.com'),
('Airport Terminal', '789 Terminal Rd', 'Chicago', 'IL', '60601', '+1-555-0103', 'airport@sn15.com')
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
('EMP001', 'John', 'Smith', 'john.smith@sn15.com', '+1-555-1001', (SELECT id FROM positions WHERE title = 'Store Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-01-15', 55000.00, true, '123 Oak St', 'New York', 'NY', '10001', 'Jane Smith', '+1-555-2001'),
('EMP002', 'Sarah', 'Johnson', 'sarah.johnson@sn15.com', '+1-555-1002', (SELECT id FROM positions WHERE title = 'Assistant Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-03-01', 45000.00, true, '456 Maple Ave', 'New York', 'NY', '10002', 'Mike Johnson', '+1-555-2002'),
('EMP003', 'Mike', 'Davis', 'mike.davis@sn15.com', '+1-555-1003', (SELECT id FROM positions WHERE title = 'Barista' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-02-15', 32000.00, true, '789 Pine St', 'New York', 'NY', '10003', 'Lisa Davis', '+1-555-2003'),
('EMP004', 'Emily', 'Wilson', 'emily.wilson@sn15.com', '+1-555-1004', (SELECT id FROM positions WHERE title = 'Cashier' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-04-01', 28000.00, true, '321 Elm St', 'New York', 'NY', '10004', 'David Wilson', '+1-555-2004'),
('EMP005', 'Robert', 'Brown', 'robert.brown@sn15.com', '+1-555-1005', (SELECT id FROM positions WHERE title = 'Store Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-01-20', 55000.00, true, '654 Cedar Ave', 'Los Angeles', 'CA', '90210', 'Maria Brown', '+1-555-2005'),
('EMP006', 'Lisa', 'Garcia', 'lisa.garcia@sn15.com', '+1-555-1006', (SELECT id FROM positions WHERE title = 'Kitchen Staff' LIMIT 1), (SELECT id FROM departments WHERE name = 'Kitchen' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-03-15', 30000.00, true, '987 Birch Blvd', 'Los Angeles', 'CA', '90211', 'Carlos Garcia', '+1-555-2006'),
('EMP007', 'David', 'Miller', 'david.miller@sn15.com', '+1-555-1007', (SELECT id FROM positions WHERE title = 'Barista' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-05-01', 32000.00, true, '147 Walnut St', 'Los Angeles', 'CA', '90212', 'Anna Miller', '+1-555-2007'),
('EMP008', 'Jennifer', 'Martinez', 'jennifer.martinez@sn15.com', '+1-555-1008', (SELECT id FROM positions WHERE title = 'Assistant Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), '2023-02-01', 45000.00, true, '258 Spruce Ln', 'Chicago', 'IL', '60601', 'Luis Martinez', '+1-555-2008')
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
-- 7. PAYROLL SYSTEM TABLES
-- ============================================

-- Create employee types table (hourly, salary, temporary, consultant)
CREATE TABLE IF NOT EXISTS employee_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(50) NOT NULL UNIQUE,
    code VARCHAR(20) NOT NULL UNIQUE,
    description TEXT,
    payment_type VARCHAR(20) NOT NULL CHECK (payment_type IN ('hourly', 'salary', 'temporary', 'consultant')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create payroll cycles table
CREATE TABLE IF NOT EXISTS payroll_cycles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    pay_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'processing', 'completed', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(start_date, end_date)
);

-- Create leave types table
CREATE TABLE IF NOT EXISTS leave_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    code VARCHAR(20) NOT NULL UNIQUE,
    description TEXT,
    is_paid BOOLEAN DEFAULT FALSE,
    requires_approval BOOLEAN DEFAULT TRUE,
    max_days_per_year INTEGER,
    carry_forward_days INTEGER DEFAULT 0,
    color VARCHAR(7) DEFAULT '#007bff', -- Hex color for UI
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create leave requests table
CREATE TABLE IF NOT EXISTS leave_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    leave_type_id UUID REFERENCES leave_types(id) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_days DECIMAL(5,2) NOT NULL,
    reason TEXT,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    approved_by UUID REFERENCES staff(id),
    approved_at TIMESTAMP,
    comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create timesheets table
CREATE TABLE IF NOT EXISTS timesheets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    payroll_cycle_id UUID REFERENCES payroll_cycles(id),
    date DATE NOT NULL,
    clock_in TIMESTAMP,
    clock_out TIMESTAMP,
    total_hours DECIMAL(6,2) DEFAULT 0,
    regular_hours DECIMAL(6,2) DEFAULT 0,
    overtime_hours DECIMAL(6,2) DEFAULT 0,
    break_hours DECIMAL(6,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'rejected')),
    notes TEXT,
    approved_by UUID REFERENCES staff(id),
    approved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, date)
);

-- Create breaks table
CREATE TABLE IF NOT EXISTS breaks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timesheet_id UUID REFERENCES timesheets(id) NOT NULL,
    break_type VARCHAR(50) NOT NULL DEFAULT 'regular',
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_minutes INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create employee pay rates table
CREATE TABLE IF NOT EXISTS employee_pay_rates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    employee_type_id UUID REFERENCES employee_types(id) NOT NULL,
    hourly_rate DECIMAL(10,2),
    annual_salary DECIMAL(12,2),
    overtime_rate DECIMAL(10,2), -- multiplier, e.g., 1.5 for time and half
    effective_date DATE NOT NULL,
    end_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, effective_date)
);

-- Create payroll entries table (calculated payroll data)
CREATE TABLE IF NOT EXISTS payroll_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    payroll_cycle_id UUID REFERENCES payroll_cycles(id) NOT NULL,
    employee_type_id UUID REFERENCES employee_types(id) NOT NULL,
    regular_hours DECIMAL(6,2) DEFAULT 0,
    overtime_hours DECIMAL(6,2) DEFAULT 0,
    total_hours DECIMAL(6,2) DEFAULT 0,
    regular_pay DECIMAL(10,2) DEFAULT 0,
    overtime_pay DECIMAL(10,2) DEFAULT 0,
    gross_pay DECIMAL(10,2) DEFAULT 0,
    deductions DECIMAL(10,2) DEFAULT 0,
    net_pay DECIMAL(10,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'calculated' CHECK (status IN ('calculated', 'approved', 'paid', 'cancelled')),
    processed_at TIMESTAMP,
    paid_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, payroll_cycle_id)
);

-- Create payments table (actual payment records)
CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    payroll_entry_id UUID REFERENCES payroll_entries(id) NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    payment_reference VARCHAR(100),
    amount DECIMAL(10,2) NOT NULL,
    payment_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'failed', 'cancelled')),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create holidays table
CREATE TABLE IF NOT EXISTS holidays (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    is_recurring BOOLEAN DEFAULT FALSE,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date)
);

-- Create leave balances table
CREATE TABLE IF NOT EXISTS leave_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    leave_type_id UUID REFERENCES leave_types(id) NOT NULL,
    year INTEGER NOT NULL,
    allocated_days DECIMAL(5,2) DEFAULT 0,
    used_days DECIMAL(5,2) DEFAULT 0,
    carried_forward DECIMAL(5,2) DEFAULT 0,
    remaining_days DECIMAL(5,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, leave_type_id, year)
);

-- ============================================
-- 8. PAYROLL SYSTEM INDEXES
-- ============================================

-- Timesheets indexes
CREATE INDEX IF NOT EXISTS idx_timesheets_staff_date ON timesheets(staff_id, date);
CREATE INDEX IF NOT EXISTS idx_timesheets_payroll_cycle ON timesheets(payroll_cycle_id);
CREATE INDEX IF NOT EXISTS idx_timesheets_status ON timesheets(status);

-- Leave requests indexes
CREATE INDEX IF NOT EXISTS idx_leave_requests_staff ON leave_requests(staff_id);
CREATE INDEX IF NOT EXISTS idx_leave_requests_dates ON leave_requests(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_leave_requests_status ON leave_requests(status);

-- Payroll entries indexes
CREATE INDEX IF NOT EXISTS idx_payroll_entries_staff_cycle ON payroll_entries(staff_id, payroll_cycle_id);
CREATE INDEX IF NOT EXISTS idx_payroll_entries_status ON payroll_entries(status);

-- Payments indexes
CREATE INDEX IF NOT EXISTS idx_payments_payroll_entry ON payments(payroll_entry_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);

-- Breaks indexes
CREATE INDEX IF NOT EXISTS idx_breaks_timesheet ON breaks(timesheet_id);
CREATE INDEX IF NOT EXISTS idx_breaks_times ON breaks(start_time, end_time);

-- ============================================
-- 9. PAYROLL SYSTEM SAMPLE DATA
-- ============================================

-- Insert employee types
INSERT INTO employee_types (name, code, description, payment_type, is_active) VALUES
('Full-time Salaried', 'FT_SALARIED', 'Regular full-time employees paid annual salary', 'salary', true),
('Part-time Hourly', 'PT_HOURLY', 'Part-time employees paid hourly wages', 'hourly', true),
('Temporary Help', 'TEMPORARY', 'Temporary seasonal or project-based workers', 'temporary', true),
('Consultant', 'CONSULTANT', 'External consultants and contractors', 'consultant', true)
ON CONFLICT DO NOTHING;

-- Insert leave types
INSERT INTO leave_types (name, code, description, is_paid, requires_approval, max_days_per_year, carry_forward_days, color) VALUES
('Annual Vacation', 'VACATION', 'Paid annual vacation leave', true, true, 15, 5, '#28a745'),
('Sick Leave', 'SICK', 'Paid sick leave for illness', true, true, 10, 0, '#dc3545'),
('Personal Leave', 'PERSONAL', 'Paid personal leave', true, true, 3, 0, '#ffc107'),
('Unpaid Leave', 'UNPAID', 'Unpaid leave of absence', false, true, NULL, 0, '#6c757d'),
('Maternity Leave', 'MATERNITY', 'Paid maternity leave', true, true, 84, 0, '#e83e8c'),
('Paternity Leave', 'PATERNITY', 'Paid paternity leave', true, true, 10, 0, '#17a2b8'),
('Bereavement Leave', 'BEREAVEMENT', 'Paid bereavement leave', true, false, 3, 0, '#343a40'),
('Holiday', 'HOLIDAY', 'Company recognized holidays', true, false, NULL, 0, '#007bff'),
('Jury Duty', 'JURY_DUTY', 'Paid time for jury duty', true, false, NULL, 0, '#6610f2')
ON CONFLICT DO NOTHING;

-- Insert holidays
INSERT INTO holidays (name, date, is_recurring, description) VALUES
('New Year''s Day', '2025-01-01', true, 'New Year''s Day holiday'),
('Martin Luther King Jr. Day', '2025-01-20', true, 'MLK Day holiday'),
('Memorial Day', '2025-05-26', true, 'Memorial Day holiday'),
('Independence Day', '2025-07-04', true, 'Fourth of July holiday'),
('Labor Day', '2025-09-01', true, 'Labor Day holiday'),
('Thanksgiving Day', '2025-11-27', true, 'Thanksgiving holiday'),
('Christmas Day', '2025-12-25', true, 'Christmas holiday')
ON CONFLICT DO NOTHING;

-- Insert payroll cycles (for next few months)
INSERT INTO payroll_cycles (name, start_date, end_date, pay_date, status) VALUES
('October 2025 Bi-weekly 1', '2025-10-01', '2025-10-14', '2025-10-18', 'draft'),
('October 2025 Bi-weekly 2', '2025-10-15', '2025-10-28', '2025-11-01', 'draft'),
('November 2025 Bi-weekly 1', '2025-10-29', '2025-11-11', '2025-11-15', 'draft'),
('November 2025 Bi-weekly 2', '2025-11-12', '2025-11-25', '2025-11-29', 'draft')
ON CONFLICT DO NOTHING;

-- Insert employee pay rates for sample staff
INSERT INTO employee_pay_rates (staff_id, employee_type_id, hourly_rate, annual_salary, overtime_rate, effective_date, is_active) VALUES
((SELECT id FROM staff WHERE employee_id = 'EMP001'), (SELECT id FROM employee_types WHERE code = 'FT_SALARIED'), NULL, 55000.00, NULL, '2023-01-15', true),
((SELECT id FROM staff WHERE employee_id = 'EMP002'), (SELECT id FROM employee_types WHERE code = 'FT_SALARIED'), NULL, 45000.00, NULL, '2023-03-01', true),
((SELECT id FROM staff WHERE employee_id = 'EMP003'), (SELECT id FROM employee_types WHERE code = 'PT_HOURLY'), 16.50, NULL, 1.5, '2023-02-15', true),
((SELECT id FROM staff WHERE employee_id = 'EMP004'), (SELECT id FROM employee_types WHERE code = 'PT_HOURLY'), 14.25, NULL, 1.5, '2023-04-01', true),
((SELECT id FROM staff WHERE employee_id = 'EMP005'), (SELECT id FROM employee_types WHERE code = 'FT_SALARIED'), NULL, 55000.00, NULL, '2023-01-20', true),
((SELECT id FROM staff WHERE employee_id = 'EMP006'), (SELECT id FROM employee_types WHERE code = 'PT_HOURLY'), 15.00, NULL, 1.5, '2023-03-15', true),
((SELECT id FROM staff WHERE employee_id = 'EMP007'), (SELECT id FROM employee_types WHERE code = 'PT_HOURLY'), 16.50, NULL, 1.5, '2023-05-01', true),
((SELECT id FROM staff WHERE employee_id = 'EMP008'), (SELECT id FROM employee_types WHERE code = 'FT_SALARIED'), NULL, 45000.00, NULL, '2023-02-01', true)
ON CONFLICT DO NOTHING;

-- Insert leave balances for current year
INSERT INTO leave_balances (staff_id, leave_type_id, year, allocated_days, used_days, remaining_days) VALUES
((SELECT id FROM staff WHERE employee_id = 'EMP001'), (SELECT id FROM leave_types WHERE code = 'VACATION'), 2025, 15.0, 5.0, 10.0),
((SELECT id FROM staff WHERE employee_id = 'EMP001'), (SELECT id FROM leave_types WHERE code = 'SICK'), 2025, 10.0, 2.0, 8.0),
((SELECT id FROM staff WHERE employee_id = 'EMP002'), (SELECT id FROM leave_types WHERE code = 'VACATION'), 2025, 15.0, 3.0, 12.0),
((SELECT id FROM staff WHERE employee_id = 'EMP002'), (SELECT id FROM leave_types WHERE code = 'SICK'), 2025, 10.0, 1.0, 9.0)
ON CONFLICT DO NOTHING;

-- Insert sample timesheets
INSERT INTO timesheets (staff_id, date, clock_in, clock_out, total_hours, regular_hours, break_hours, status) VALUES
((SELECT id FROM staff WHERE employee_id = 'EMP003'), '2025-10-01', '2025-10-01 08:00:00', '2025-10-01 16:30:00', 8.0, 8.0, 0.5, 'approved'),
((SELECT id FROM staff WHERE employee_id = 'EMP004'), '2025-10-01', '2025-10-01 09:00:00', '2025-10-01 17:00:00', 8.0, 8.0, 0.5, 'approved'),
((SELECT id FROM staff WHERE employee_id = 'EMP006'), '2025-10-01', '2025-10-01 10:00:00', '2025-10-01 18:00:00', 8.0, 8.0, 0.5, 'approved'),
((SELECT id FROM staff WHERE employee_id = 'EMP007'), '2025-10-01', '2025-10-01 11:00:00', '2025-10-01 19:00:00', 8.0, 8.0, 0.5, 'approved')
ON CONFLICT DO NOTHING;

-- Insert sample breaks
INSERT INTO breaks (timesheet_id, break_type, start_time, end_time, duration_minutes, notes) VALUES
((SELECT id FROM timesheets WHERE staff_id = (SELECT id FROM staff WHERE employee_id = 'EMP003') AND date = '2025-10-01'), 'lunch', '2025-10-01 12:00:00', '2025-10-01 12:30:00', 30, 'Lunch break'),
((SELECT id FROM timesheets WHERE staff_id = (SELECT id FROM staff WHERE employee_id = 'EMP004') AND date = '2025-10-01'), 'lunch', '2025-10-01 12:30:00', '2025-10-01 13:00:00', 30, 'Lunch break')
ON CONFLICT DO NOTHING;

-- ============================================
-- SETUP COMPLETE
-- ============================================
-- Database: sipnsnack
-- User: sipnsnack_user
-- Tables created: 17
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
