-- pgAdmin-friendly script to make a user a root user (allow all permissions)
-- Instructions:
-- 1) Edit the v_email value below to your user's email
-- 2) Run this script in pgAdmin Query Tool

DO $$
DECLARE
    v_email    text := 'snehitha@sn15.ai'; -- CHANGE THIS
    v_user_id  uuid;
BEGIN
    -- Ensure user exists and is active
    INSERT INTO users (email, full_name, is_active)
    VALUES (v_email, 'Root User', TRUE)
    ON CONFLICT (email) DO UPDATE
    SET is_active = EXCLUDED.is_active,
        full_name = COALESCE(users.full_name, EXCLUDED.full_name);

    SELECT id INTO v_user_id FROM users WHERE email = v_email LIMIT 1;

    -- Remove any user-level DENY rules
    DELETE FROM user_permissions
    WHERE user_id = v_user_id AND effect = 'deny';

    -- Grant ALLOW for all permissions
    INSERT INTO user_permissions (user_id, permission_id, effect)
    SELECT v_user_id, p.id, 'allow'
    FROM permissions p
    ON CONFLICT (user_id, permission_id) DO UPDATE
    SET effect = EXCLUDED.effect;

    RAISE NOTICE 'Root permissions granted to %', v_email;
END
$$ LANGUAGE plpgsql;

-- Verification
SELECT u.email, COUNT(*) AS total_allow_permissions
FROM users u
JOIN user_permissions up ON up.user_id = u.id AND up.effect = 'allow'
WHERE u.email = 'snehitha@sn15.ai'  -- keep in sync with v_email above
GROUP BY u.email;


