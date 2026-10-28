#!/usr/bin/env python3
# Run by install-common.sh --with-nbgrader, after nbgrader and
# ngshare_exchange are installed. Every patch must either apply or already
# be applied: a target that no longer matches (e.g. after an nbgrader
# version bump) fails the build instead of shipping an unpatched image.
import glob
import importlib.util
import os
import sys


def package_dir(name):
    # find_spec locates without importing: ngshare_exchange reads $USER at
    # import time, which isn't set during a docker build.
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin is None:
        sys.exit(f"patch_formgrader.py: {name} is not installed")
    return os.path.dirname(spec.origin)


NBGRADER_DIR = package_dir("nbgrader")
FORMGRADER_DIR = os.path.join(NBGRADER_DIR, "server_extensions", "formgrader")
TEMPLATE_DIR = os.path.join(FORMGRADER_DIR, "templates") + "/"
APIHANDLERS = os.path.join(FORMGRADER_DIR, "apihandlers.py")
JS_DIR = os.path.join(FORMGRADER_DIR, "static", "js") + "/"
EXCHANGE = os.path.join(package_dir("ngshare_exchange"), "exchange.py")

failures = []


def patch_file(path, old, new, label, allow_multiple=False):
    try:
        with open(path) as f:
            content = f.read()
    except OSError as e:
        print(f"[FAIL] {label}: {e}")
        failures.append(label)
        return
    if new in content:
        print(f"[SKIP] {label}: already patched")
        return
    found = content.count(old)
    if found == 0 or (found > 1 and not allow_multiple):
        print(f"[FAIL] {label}: expected string found {found} times in {path}")
        failures.append(label)
        return
    with open(path, "w") as f:
        f.write(content.replace(old, new))
    print(f"[OK]   {label}: patched successfully")


# 1. Remove Edit Student column header from manage_students.tpl
patch_file(
    path=TEMPLATE_DIR + "manage_students.tpl",
    old='  <th class="text-center no-sort">Edit Student</th>',
    new='{# Edit Student column disabled - use ngshare-course-management CLI #}',
    label="manage_students.tpl: remove Edit Student column header"
)

# 2. Remove Add new student footer from manage_students.tpl
patch_file(
    path=TEMPLATE_DIR + "manage_students.tpl",
    old="""  <td colspan="5">
    <span class="glyphicon glyphicon-plus" aria-hidden="true"></span>
    <a href="#" onClick="createStudentModal();">Add new student...</a>
  </td>""",
    new="""  <td colspan="5">
    {# Add new student disabled - use ngshare-course-management CLI #}
  </td>""",
    label="manage_students.tpl: remove Add new student button"
)

# 3. Block PUT /api/student in apihandlers.py
patch_file(
    path=APIHANDLERS,
    old="""    def put(self, student_id):
        data = self.get_json_body()
        student = {""",
    new="""    def put(self, student_id):
        raise web.HTTPError(403, reason="Use ngshare-course-management CLI instead.")

    def put_DISABLED(self, student_id):
        data = self.get_json_body()
        student = {""",
    label="apihandlers.py: block PUT /api/student"
)

# 4. Remove Edit button from manage_students.js
patch_file(
    path=JS_DIR + "manage_students.js",
    old="""        // edit metadata
        this.$edit.append($("<a/>")
            .attr("href", "#")
            .click(_.bind(this.openModal, this))
            .append($("<span/>")
                .addClass("glyphicon glyphicon-pencil")
                .attr("aria-hidden", "true")));""",
    new="""        // edit metadata disabled - use ngshare-course-management CLI""",
    label="manage_students.js: remove Edit button"
)

# 5. Disable openModal function in manage_students.js
patch_file(
    path=JS_DIR + "manage_students.js",
    old="""    openModal: function () {
        var body = $("<table/>").addClass("table table-striped form-table");
        var tablebody = $("<tbody/>");
        body.append(tablebody);
        var id = $("<tr/>");
        tablebody.append(id);
        id.append($("<td/>").addClass("align-middle").text("Student ID"));
        id.append($("<td/>").append($("<input/>")
            .addClass("modal-id")
            .attr("type", "text")
            .attr("disabled", "disabled")));

        var first_name = $("<tr/>");
        tablebody.append(first_name);
        first_name.append($("<td/>").addClass("align-middle").text("First name (optional)"));
        first_name.append($("<td/>").append($("<input/>").addClass("modal-first-name").attr("type", "text")));

        var last_name = $("<tr/>");
        tablebody.append(last_name);
        last_name.append($("<td/>").addClass("align-middle").text("Last name (optional)"));
        last_name.append($("<td/>").append($("<input/>").addClass("modal-last-name").attr("type", "text")));

        var email = $("<tr/>");
        tablebody.append(email);
        email.append($("<td/>").addClass("align-middle").text("Email (optional)"));
        email.append($("<td/>").append($("<input/>").addClass("modal-email").attr("type", "text")));

        var footer = $("<div/>");
        footer.append($("<button/>")
            .addClass("btn btn-primary save")
            .attr("type", "button")
            .text("Save"));
        footer.append($("<button/>")
            .addClass("btn btn-danger")
            .attr("type", "button")
            .attr("data-dismiss", "modal")
            .text("Cancel"));

        this.$modal = createModal("edit-student-modal", "Editing " + this.model.get("id"), body, footer);
        this.$modal.find("input.modal-id").val(this.model.get("id"));
        this.$modal_first_name = this.$modal.find("input.modal-first-name");
        this.$modal_first_name.val(this.model.get("first_name"));
        this.$modal_last_name = this.$modal.find("input.modal-last-name");
        this.$modal_last_name.val(this.model.get("last_name"));
        this.$modal_email = this.$modal.find("input.modal-email");
        this.$modal_email.val(this.model.get("email"));
        this.$modal_save = this.$modal.find("button.save");
        this.$modal_save.click(_.bind(this.save, this));
    },""",
    new="""    openModal: function () {
        // disabled - use ngshare-course-management CLI
    },""",
    label="manage_students.js: disable openModal function"
)

# 6. Fix decode_dir in ngshare_exchange to create parent directories
patch_file(
    path=EXCHANGE,
    old="            with open(dest_path, 'wb') as d:",
    new="            os.makedirs(os.path.dirname(dest_path), exist_ok=True)\n            with open(dest_path, 'wb') as d:",
    label="exchange.py: fix decode_dir to create parent directories"
)

# 7. Reword the "no available formgrader services" message in Course List.
#    Course List is structurally non-functional for our ngshare-based
#    architecture (it probes for a per-course JupyterHub service that we
#    don't register - see confluence doc), so instead of hiding it we just
#    make the empty state read as expected behavior, not an error.
#    The message lives in a webpack chunk whose filename is a content hash
#    that changes on nbgrader version bumps, so locate it by content in both
#    copies of the labextension (installed and package data).
COURSE_LIST_OLD = 'There are no available formgrader services.'
COURSE_LIST_NEW = 'Course List is not used here - use Assignment List instead.'
COURSE_LIST_JS_PATHS = []
for _static in (
    os.path.join(sys.prefix, "share", "jupyter", "labextensions", "@jupyter", "nbgrader", "static"),
    os.path.join(NBGRADER_DIR, "labextension", "static"),
):
    for _path in sorted(glob.glob(os.path.join(_static, "*.js"))):
        with open(_path) as f:
            _content = f.read()
        if COURSE_LIST_OLD in _content or COURSE_LIST_NEW in _content:
            COURSE_LIST_JS_PATHS.append(_path)
if not COURSE_LIST_JS_PATHS:
    print("[FAIL] course_list JS: no labextension chunk contains the empty-state message")
    failures.append("course_list JS")
for _path in COURSE_LIST_JS_PATHS:
    patch_file(
        path=_path,
        old=COURSE_LIST_OLD,
        new=COURSE_LIST_NEW,
        label=f"course_list JS ({_path}): reword empty-state message",
        allow_multiple=True,
    )

if failures:
    sys.exit(f"patch_formgrader.py: {len(failures)} patch(es) failed: {', '.join(failures)}")
