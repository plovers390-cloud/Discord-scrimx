from tortoise import fields
from tortoise.models import Model


class RoleWaiting(Model):
    class Meta:
        table = "role_waiting"

    id = fields.IntField(pk=True)
    guild_id = fields.BigIntField()
    channel_id = fields.BigIntField()
    role_id = fields.BigIntField()
    
    # Store time as "HH:MM" string (e.g., "13:57")
    trigger_time = fields.CharField(max_length=5)  # Format: HH:MM
    
    max_users = fields.IntField()  # Number of users to give role
    given_users = fields.JSONField(default=list)  # Users who got the role today
    is_active = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    last_triggered = fields.DateField(null=True)  # Track last trigger date
    ping_role_id = fields.BigIntField(null=True)  # New field
    ping_type = fields.CharField(max_length=20, default="here")