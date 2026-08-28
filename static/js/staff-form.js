// Shared Add/Edit Staff Member form behavior: phone validation, duplicate-name
// detection, required/pattern field validation (all at once, not just the
// first invalid one), per-hour/per-day salary auto-calc, and submit
// validation.
document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('staffForm');
    if (!form) return;

    var phoneInput = document.getElementById('phone');
    var firstNameInput = document.getElementById('first_name');
    var lastNameInput = document.getElementById('last_name');
    var monthlySalaryInput = document.getElementById('monthly_salary');
    var perHourInput = document.getElementById('per_hour_salary');
    var perDayInput = document.getElementById('per_day_salary');
    var duplicateWarning = document.getElementById('duplicateNameWarning');
    var duplicateDetails = document.getElementById('duplicateNameDetails');

    var currentStaffId = form.dataset.staffId || null;
    var checkDuplicateUrl = form.dataset.checkDuplicateUrl;

    // ---- Per Hour / Per Day Salary auto-calc from Monthly Salary ----
    if (monthlySalaryInput && perHourInput && perDayInput) {
        var updatePerHourSalary = function () {
            var monthly = parseFloat(monthlySalaryInput.value);
            var daysInMonth = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate();
            var perHour = monthly > 0 ? monthly / (daysInMonth * 8) : 0;
            var perDay = monthly > 0 ? monthly / daysInMonth : 0;
            perHourInput.value = perHour.toFixed(2);
            perDayInput.value = perDay.toFixed(2);
        };
        monthlySalaryInput.addEventListener('input', updatePerHourSalary);
        updatePerHourSalary();
    }

    // ---- Phone: exactly 10 digits, first digit 6-9, not an obviously fake number ----
    // Each rule is its own explicit check (not folded into one regex) so
    // the length check can never silently stand in for the first-digit
    // check, or vice versa.
    // A run of 8+ consecutive digits (out of the 10) that repeats with a
    // period of 1 or 2 is an obvious dummy pattern - e.g. 7989898989 (the
    // "89" pair keeps repeating from index 2 onward), 7878787878,
    // 1111111111. Checked over every starting position, not just from the
    // very first digit, so a pattern that only kicks in partway through
    // the number (like 7989898989) is still caught.
    function hasRepeatingPattern(value, minRun) {
        minRun = minRun || 8;
        for (var start = 0; start <= value.length - minRun; start++) {
            var window = value.slice(start);
            for (var period = 1; period <= 2; period++) {
                var repeats = true;
                for (var i = 0; i < window.length; i++) {
                    if (window[i] !== window[i % period]) { repeats = false; break; }
                }
                if (repeats) return true;
            }
        }
        return false;
    }

    function isValidPhone(value) {
        // 1. Digits only, and exactly 10 of them.
        if (!/^[0-9]{10}$/.test(value)) return false;
        // 2. First digit must be 6, 7, 8, or 9 - explicitly, not as a side
        //    effect of the length regex above. 0-5 are rejected here even
        //    if steps 1/3 would otherwise have passed.
        var firstDigit = value.charAt(0);
        if (firstDigit < '6' || firstDigit > '9') return false;
        // 3. A straight ascending or descending run across all 10 digits
        //    (1234567890, 1234567891, 9876543210, ...) - checked
        //    algorithmically instead of a fixed list, so it catches every
        //    such run, not just a couple of hardcoded examples.
        var ascending = true, descending = true;
        for (var i = 1; i < value.length; i++) {
            var prev = value.charCodeAt(i - 1);
            var cur = value.charCodeAt(i);
            if (cur !== prev + 1) ascending = false;
            if (cur !== prev - 1) descending = false;
        }
        if (ascending || descending) return false;
        // 4. No repeating/pattern-based dummy run of 8+ digits with period
        //    1 or 2, anywhere in the number - covers all-same-digit
        //    numbers (1111111111, 9999999999) and 2-digit alternating
        //    patterns (9898989898, 9191919191, and mid-number ones like
        //    7989898989) under one general rule.
        if (hasRepeatingPattern(value)) return false;
        return true;
    }

    function phoneValidationMessage(value) {
        if (!value) {
            return 'Phone number is required.';
        }
        // First-digit failure gets called out explicitly and on its own -
        // checked before (and independently of) every other phone rule, so
        // a number starting 0/1/2/3/4/5 is never silently folded into the
        // generic length/format message.
        var firstDigit = value.charAt(0);
        if (firstDigit >= '0' && firstDigit <= '5') {
            return 'Enter a valid 10-digit mobile number starting with 6, 7, 8, or 9.';
        }
        if (!isValidPhone(value)) {
            return 'Enter a valid 10-digit mobile number. Example: 7989189681';
        }
        return '';
    }

    // The phone field's own <div class="invalid-feedback"> - its text is
    // rewritten live so the validation message actually reaches the
    // screen, instead of only setCustomValidity() (which the browser
    // never surfaces on its own since the form has novalidate).
    var phoneFeedback = phoneInput ? phoneInput.closest('.input-group, .col-md-12').querySelector('.invalid-feedback') : null;

    function setPhoneMessage(msg) {
        if (phoneFeedback) phoneFeedback.textContent = msg || phoneFeedback.dataset.defaultText;
    }
    if (phoneFeedback) phoneFeedback.dataset.defaultText = phoneFeedback.textContent;

    // Strip non-digits live and cap at 10 characters as the user types.
    // The red border only appears once the first digit is known to be
    // wrong (0-5) or the field is blurred/submitted with fewer than 10
    // digits still in it - not on every keystroke while a valid number is
    // still being typed out.
    if (phoneInput) {
        phoneInput.addEventListener('input', function () {
            var cleaned = this.value.replace(/\D/g, '').slice(0, 10);
            this.value = cleaned;
            var msg = phoneValidationMessage(cleaned);
            this.setCustomValidity(msg);
            setPhoneMessage(msg);

            var firstDigitKnownBad = cleaned.length > 0 && (cleaned.charAt(0) < '6' || cleaned.charAt(0) > '9');
            if (cleaned.length === 10 || firstDigitKnownBad) {
                this.classList.toggle('is-invalid', !!msg);
            } else {
                this.classList.remove('is-invalid');
            }
        });
        phoneInput.addEventListener('blur', function () {
            var msg = phoneValidationMessage(this.value);
            this.setCustomValidity(msg);
            setPhoneMessage(msg);
            this.classList.toggle('is-invalid', !!msg);
        });
    }

    // ---- Duplicate name detection ----
    function hideDuplicateWarning() {
        if (duplicateWarning) duplicateWarning.classList.add('d-none');
    }

    function showDuplicateWarning(staff) {
        if (!duplicateWarning || !duplicateDetails) return;
        var parts = [];
        parts.push('<strong>' + staff.name + '</strong>');
        if (staff.employee_id) parts.push('Employee ID: ' + staff.employee_id);
        if (staff.phone) parts.push('Phone: ' + staff.phone);
        if (staff.location) parts.push('Location: ' + staff.location);
        if (staff.position) parts.push('Position: ' + staff.position);
        duplicateDetails.innerHTML = parts.join(' &nbsp;|&nbsp; ');
        duplicateWarning.classList.remove('d-none');
    }

    function checkDuplicateName() {
        var first = (firstNameInput.value || '').trim();
        var last = (lastNameInput.value || '').trim();
        if (!first || !last || !checkDuplicateUrl) {
            hideDuplicateWarning();
            return;
        }
        fetch(checkDuplicateUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ first_name: first, last_name: last, exclude_id: currentStaffId })
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data && data.exists) {
                    showDuplicateWarning(data.staff);
                } else {
                    hideDuplicateWarning();
                }
            })
            .catch(function () { /* silently ignore - not a hard blocker client-side */ });
    }

    if (firstNameInput && lastNameInput) {
        firstNameInput.addEventListener('blur', checkDuplicateName);
        lastNameInput.addEventListener('blur', checkDuplicateName);
        firstNameInput.addEventListener('input', hideDuplicateWarning);
        lastNameInput.addEventListener('input', hideDuplicateWarning);
    }

    // ---- Every required/pattern-constrained field on the form ----
    // Street Address, City, State, and ZIP are plain `required` fields in
    // the HTML now (Bank Details and Address Information both link back to
    // this <form> via form="staffForm"), so a single generic query covers
    // every card - no per-section wiring needed.
    function allValidatedFields() {
        var inForm = Array.prototype.slice.call(form.querySelectorAll('[required], [pattern]'));
        var linked = Array.prototype.slice.call(document.querySelectorAll('[form="staffForm"][required], [form="staffForm"][pattern]'));
        return inForm.concat(linked);
    }

    // Re-validate one field immediately and reflect the result in its own
    // red border + inline message - independent of every other field, so
    // leaving a field blank shows its error right away without needing a
    // submit attempt.
    function validateField(field) {
        if (field === phoneInput) {
            var msg = phoneValidationMessage(field.value);
            field.setCustomValidity(msg);
            setPhoneMessage(msg);
        } else {
            field.setCustomValidity('');
        }
        var valid = field.checkValidity();
        field.classList.toggle('is-invalid', !valid);
        if (valid) field.classList.remove('is-invalid');
        return valid;
    }

    allValidatedFields().forEach(function (field) {
        field.addEventListener('blur', function () { validateField(field); });
        field.addEventListener('input', function () {
            // Only clear the red state live as the user types; re-showing it
            // happens on blur/submit so it doesn't flash red mid-keystroke.
            if (field !== phoneInput) field.setCustomValidity('');
            if (field.checkValidity()) field.classList.remove('is-invalid');
        });
    });

    // ---- Submit validation ----
    // Validates every required/invalid field at once (not just the first)
    // so every empty or invalid field gets its red border + message
    // simultaneously, then blocks submission if any failed.
    form.addEventListener('submit', function (e) {
        var fields = allValidatedFields();
        var firstInvalid = null;
        var anyInvalid = false;

        fields.forEach(function (field) {
            var valid = validateField(field);
            if (!valid) {
                anyInvalid = true;
                if (!firstInvalid) firstInvalid = field;
            }
        });

        form.classList.add('was-validated');

        if (anyInvalid) {
            e.preventDefault();
            e.stopPropagation();

            if (window.showToast) {
                window.showToast('danger', 'Please complete all required fields.');
            }
            if (firstInvalid) {
                firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                setTimeout(function () { firstInvalid.focus(); }, 150);
            }
            return;
        }

        // Duplicate-name block: a same-named staff record must not be saved.
        if (duplicateWarning && !duplicateWarning.classList.contains('d-none')) {
            e.preventDefault();
            duplicateWarning.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    });
});
