import arrow
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import TimestampSigner
from wtforms import validators, IntegerField
from wtforms.fields.html5 import EmailField

from app import parallel_limiter
from app.config import MAILBOX_SECRET, JOB_DELETE_MAILBOX
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.log import LOG
from app.mailbox_utils import create_mailbox_and_send_verification, verify_mailbox
from app.models import Mailbox, Job
from app.utils import CSRFValidationForm


class NewMailboxForm(FlaskForm):
    email = EmailField(
        "email", validators=[validators.DataRequired(), validators.Email()]
    )


class DeleteMailboxForm(FlaskForm):
    mailbox_id = IntegerField(
        validators=[validators.DataRequired()],
    )
    transfer_mailbox_id = IntegerField()


@dashboard_bp.route("/mailbox", methods=["GET", "POST"])
@login_required
@parallel_limiter.lock(only_when=lambda: request.method == "POST")
def mailbox_route():
    mailboxes = (
        Mailbox.filter_by(user_id=current_user.id)
        .order_by(Mailbox.created_at.desc())
        .all()
    )

    new_mailbox_form = NewMailboxForm()
    csrf_form = CSRFValidationForm()
    delete_mailbox_form = DeleteMailboxForm()

    if request.method == "POST":
        if request.form.get("form-name") == "delete":
            if not delete_mailbox_form.validate():
                flash("Invalid request", "warning")
                return redirect(request.url)
            mailbox = Mailbox.get(delete_mailbox_form.mailbox_id.data)

            if not mailbox or mailbox.user_id != current_user.id:
                flash("Invalid mailbox. Refresh the page", "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            if mailbox.id == current_user.default_mailbox_id:
                flash("You cannot delete default mailbox", "error")
                return redirect(url_for("dashboard.mailbox_route"))

            transfer_mailbox_id = delete_mailbox_form.transfer_mailbox_id.data
            if transfer_mailbox_id and transfer_mailbox_id > 0:
                transfer_mailbox = Mailbox.get(transfer_mailbox_id)

                if not transfer_mailbox or transfer_mailbox.user_id != current_user.id:
                    flash(
                        "You must transfer the aliases to a mailbox you own.", "error"
                    )
                    return redirect(url_for("dashboard.mailbox_route"))

                if transfer_mailbox.id == mailbox.id:
                    flash(
                        "You can not transfer the aliases to the mailbox you want to delete.",
                        "error",
                    )
                    return redirect(url_for("dashboard.mailbox_route"))

                if not transfer_mailbox.verified:
                    flash("Your new mailbox is not verified", "error")
                    return redirect(url_for("dashboard.mailbox_route"))

            # Schedule delete account job
            LOG.w(
                f"schedule delete mailbox job for {mailbox.id} with transfer to mailbox {transfer_mailbox_id}"
            )
            Job.create(
                name=JOB_DELETE_MAILBOX,
                payload={
                    "mailbox_id": mailbox.id,
                    "transfer_mailbox_id": transfer_mailbox_id
                    if transfer_mailbox_id > 0
                    else None,
                },
                run_at=arrow.now(),
                commit=True,
            )

            flash(
                f"Mailbox {mailbox.email} scheduled for deletion."
                f"You will receive a confirmation email when the deletion is finished",
                "success",
            )

            return redirect(url_for("dashboard.mailbox_route"))
        if request.form.get("form-name") == "set-default":
            if not csrf_form.validate():
                flash("Invalid request", "warning")
                return redirect(request.url)
            mailbox_id = request.form.get("mailbox_id")
            mailbox = Mailbox.get(mailbox_id)

            if not mailbox or mailbox.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            if mailbox.id == current_user.default_mailbox_id:
                flash("This mailbox is already default one", "error")
                return redirect(url_for("dashboard.mailbox_route"))

            if not mailbox.verified:
                flash("Cannot set unverified mailbox as default", "error")
                return redirect(url_for("dashboard.mailbox_route"))

            current_user.default_mailbox_id = mailbox.id
            Session.commit()
            flash(f"Mailbox {mailbox.email} is set as Default Mailbox", "success")

            return redirect(url_for("dashboard.mailbox_route"))

        elif request.form.get("form-name") == "create":
            if not current_user.is_premium():
                flash("Only premium plan can add additional mailbox", "warning")
                return redirect(url_for("dashboard.mailbox_route"))
            mailbox_email = new_mailbox_form.email.data.lower().strip().replace(" ", "")
            (new_mailbox, error_message) = create_mailbox_and_send_verification(
                current_user, mailbox_email
            )
            if error_message is not None:
                flash(error_message, "error")
            else:
                flash(
                    f"You are going to receive an email to confirm {mailbox_email}.",
                    "success",
                )
                return redirect(
                    url_for(
                        "dashboard.mailbox_detail_route",
                        mailbox_id=new_mailbox.id,
                    )
                )

    return render_template(
        "dashboard/mailbox.html",
        mailboxes=mailboxes,
        new_mailbox_form=new_mailbox_form,
        delete_mailbox_form=delete_mailbox_form,
        csrf_form=csrf_form,
    )


@dashboard_bp.route("/mailbox_verify")
def mailbox_verify():
    s = TimestampSigner(MAILBOX_SECRET)
    mailbox_id = request.args.get("mailbox_id")

    try:
        r_id = int(s.unsign(mailbox_id, max_age=900))
    except Exception:
        flash("Invalid link. Please delete and re-add your mailbox", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    else:
        mailbox = Mailbox.get(r_id)
        if not mailbox:
            flash("Invalid link", "error")
            return redirect(url_for("dashboard.mailbox_route"))

        verify_mailbox(mailbox)

        LOG.d("Mailbox %s is verified", mailbox)

        return render_template("dashboard/mailbox_validation.html", mailbox=mailbox)
