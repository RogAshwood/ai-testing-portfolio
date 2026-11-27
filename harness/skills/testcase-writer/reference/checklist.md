# Checklist of test ideas

The team's generic test ideas. Apply each one only when the story or its acceptance criteria call for it.
Generated from harness/checklist.toml (titles and descriptions); edit there, not here.

- **C01 Permissions check (authorisation)**: Checks that a user with the right role or permission can carry out the action, and that a user without it is refused.
- **C02 Create, read, update, delete check (CRUD)**: Checks that a created, updated or deleted record is really saved: it reads back with the right values, only the changed fields change, and a deleted record can no longer be used.
- **C03 Missing required inputs check**: Checks what happens when each input or document the story requires is missing.
- **C04 Invalid and unusual input values check**: Checks how text that is too long or too short, special or accented characters, extra spaces, numbers of the wrong type and impossible or badly formatted dates are handled, where the story says how.
- **C05 Limits and thresholds check**: Checks every limit with a case on the limit and one just the other side, however the limit is written (in digits, in words, or relative to an event).
- **C06 Rule interactions check**: Checks what happens when two rules apply to the same input: which one takes precedence, exemptions, combined conditions and manual overrides.
- **C07 Record status changes check**: Checks that a stored record can make the status moves the story allows, and is refused a move it does not allow.
- **C08 Dates, times and period-end check**: Checks dates and times at the edges that could change the result: month, quarter and year end, 28/29 February, cut-offs, 12- and 24-hour times, midnight and time zones.
- **C09 Audit trail check**: Checks that a decision or action is recorded (who, what, when and why), not only that it happened. *(The team always expects this where the story makes or records a decision.)*
- **C10 Must-not rules check**: Checks that something the story forbids does not happen, and that an excluded item is not accepted.
- **C11 Workflow check (steps and branches)**: Checks a multi-step process end to end: each branch, changing an earlier choice, stopping and resuming, and skipping a required step.
- **C12 Performance and volume check**: Checks a response time or volume the story states. *(Not used by this team: performance is tested separately.)*
- **C13 Repeat submission check**: Checks what happens when the same item is submitted twice.
- **C14 Two users at once check (concurrency)**: Checks what happens when two users change the same record at the same time.
- **C15 Notifications check**: Checks that a notification is sent, to the right person, with the right key content.
- **C16 Personal data check (shown or masked)**: Checks who can see which personal data, and that data meant to be hidden stays masked.
- **C17 Dependent fields check**: Checks that when one value changes what another field offers or requires, the dependent field updates or is cleared.
- **C18 Log-in check (authentication)**: Checks that valid credentials let a user in, and that wrong, expired or locked credentials are refused.
- **C19 Files and attachments check**: Checks how uploads are handled: wrong file type, too large, empty or corrupt, password-protected, poor quality, too many files, and the same file twice.
