import os
import discord
import time
from discord.ext import commands, tasks
from threading import Thread
from discord import app_commands
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive  # <-- เรียกจากไฟล์ keep_alive.py

# ------------------------------
# Discord Bot Setup
# ------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------------
# โครงสร้างปาร์ตี้
# ------------------------------
parties = {
    t: {
        ch: {
            boss: []
            for boss in ["Sylph", "Undine", "Gnome", "Salamander"]
        }
        for ch in ["CH-1", "CH-2"]
    }
    for t in ["16.00", "18.00", "22.00"]
}

user_party = {}  # user_id -> (time, ch, boss, count)
party_friend_names = {
}  # (time, ch, boss) -> {user_id: [friend1, friend2,...]}

join_start_time = "12.00"  # default join start time
admin_password = "osysadmin"


# ------------------------------
# Helper: แสดงรายชื่อปาร์ตี้
# ------------------------------
async def show_party(interaction: discord.Interaction, time: str = None):
    guild = interaction.guild
    member_numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    def clean_display_name(name: str) -> str:
        import re
        if re.match(r"^\d{3,4} -", name):
            return name.split("-", 1)[1]
        return name

    def format_members_vertical_numbered(members, key):
        names = []
        added = set()
        for uid in members:
            member = guild.get_member(uid)
            display_name = clean_display_name(
                member.display_name) if member else str(uid)
            if display_name not in added:
                names.append(display_name)
                added.add(display_name)
            friends = party_friend_names.get(key, {}).get(uid, [])
            for friend in friends:
                if friend not in added:
                    names.append(friend)
                    added.add(friend)
        while len(names) < 5:
            names.append("-")
        return "\n".join(f"{member_numbers[i]} {name[:12]}"
                         for i, name in enumerate(names[:5]))

    boss_icons = {
        "Sylph": "<:wind:1417135422269689928>",
        "Undine": "<:water:1417135449172082698>",
        "Gnome": "<:earth:1417135502867300372>",
        "Salamander": "<:fire:1417135359799726160>"
    }

    times_to_show = [time] if time and time in parties else parties.keys()
    embeds = []

    for t in times_to_show:
        embed = discord.Embed(title=f"📋 เวลา {t}", color=0x9400D3)
        for ch, bosses in parties[t].items():
            value_lines = []
            for boss_group in [["Sylph", "Undine"], ["Gnome", "Salamander"]]:
                for boss in boss_group:
                    if boss in bosses:
                        key = (t, ch, boss)
                        value_lines.append(
                            f"{boss_icons[boss]} {boss}\n{format_members_vertical_numbered(bosses[boss], key)}"
                        )
            embed.add_field(name=f"{ch}",
                            value="\n\n".join(value_lines),
                            inline=True)
        embed.set_footer(text="Party System | By XeZer 😎")
        embeds.append(embed)

    for embed in embeds:
        await interaction.followup.send(embed=embed, ephemeral=True)


# ------------------------------
# UI Join View (English version)
# ------------------------------
class JoinView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.selected_time = None
        self.selected_ch = None
        self.selected_boss = None
        self.selected_count = 1

        # Time select
        self.time_select = discord.ui.Select(
            placeholder="Select Time",
            options=[discord.SelectOption(label=t) for t in parties.keys()])
        self.time_select.callback = self.time_callback
        self.add_item(self.time_select)

        # Channel select
        self.ch_select = discord.ui.Select(
            placeholder="Select Channel",
            options=[
                discord.SelectOption(label="CH-1"),
                discord.SelectOption(label="CH-2")
            ])
        self.ch_select.callback = self.ch_callback
        self.add_item(self.ch_select)

        # Boss select
        self.boss_select = discord.ui.Select(
            placeholder="Select Boss",
            options=[
                discord.SelectOption(label=boss)
                for boss in ["Sylph", "Undine", "Gnome", "Salamander"]
            ])
        self.boss_select.callback = self.boss_callback
        self.add_item(self.boss_select)

        # Count select
        self.count_select = discord.ui.Select(
            placeholder="Select number of members (1-5)",
            options=[discord.SelectOption(label=str(i)) for i in range(1, 6)])
        self.count_select.callback = self.count_callback
        self.add_item(self.count_select)

        # Confirm button
        self.confirm_button = discord.ui.Button(
            label="✅ Confirm", style=discord.ButtonStyle.green)
        self.confirm_button.callback = self.confirm_callback
        self.add_item(self.confirm_button)

        # Leave button
        self.leave_button = discord.ui.Button(label="↩️ Leave",
                                              style=discord.ButtonStyle.red)
        self.leave_button.callback = self.leave_callback
        self.add_item(self.leave_button)

        # Check Party button
        self.check_button = discord.ui.Button(
            label="🔍 Check Party", style=discord.ButtonStyle.blurple)
        self.check_button.callback = self.check_callback
        self.add_item(self.check_button)

    # ------------------------------
    # Select callbacks
    # ------------------------------
    async def time_callback(self, interaction: discord.Interaction):
        self.selected_time = self.time_select.values[0]
        await interaction.response.defer(ephemeral=True)

    async def ch_callback(self, interaction: discord.Interaction):
        self.selected_ch = self.ch_select.values[0]
        await interaction.response.defer(ephemeral=True)

    async def boss_callback(self, interaction: discord.Interaction):
        self.selected_boss = self.boss_select.values[0]
        await interaction.response.defer(ephemeral=True)

    async def count_callback(self, interaction: discord.Interaction):
        self.selected_count = int(self.count_select.values[0])
        await interaction.response.defer(ephemeral=True)

    # ------------------------------
    # Confirm Join
    # ------------------------------
    async def confirm_callback(self, interaction: discord.Interaction):
        uid = interaction.user.id

        # Prevent duplicate join
        if uid in user_party:
            await interaction.response.send_message(
                "⚠️ You are already in a party. Please leave first.",
                ephemeral=True)
            return

        # Ensure all selections are made
        if not (self.selected_time and self.selected_ch and self.selected_boss
                and self.selected_count):
            await interaction.response.send_message(
                "⚠️ Please select **Time / Channel / Boss / Member count** first.",
                ephemeral=True)
            return

        # ------------------------------
        # ✅ Check join_start_time (เวลาที่อนุญาตให้เริ่ม join)
        # ------------------------------
        now = datetime.now(timezone(timedelta(hours=7)))
        join_hour, join_min = map(int, join_start_time.split("."))
        join_dt = now.replace(hour=join_hour,
                              minute=join_min,
                              second=0,
                              microsecond=0)

        if now < join_dt:
            await interaction.response.send_message(
                f"⏰ It’s not time to join yet! Please wait until **{join_start_time}**.",
                ephemeral=True)
            return

        key = (self.selected_time, self.selected_ch, self.selected_boss)
        members = parties[self.selected_time][self.selected_ch][
            self.selected_boss]
        remaining_slots = 5 - len(members)

        # Check available slots before showing modal
        if remaining_slots < self.selected_count:
            await interaction.response.send_message(
                f"❌ Only {remaining_slots} slot(s) left, but you selected {self.selected_count}.",
                ephemeral=True)
            return

        # If party size > 1 → open friend modal
        if self.selected_count > 1:
            await interaction.response.send_modal(FriendModal(self))
        else:
            # Double-check slot before joining
            remaining_slots = 5 - len(parties[self.selected_time][
                self.selected_ch][self.selected_boss])
            if remaining_slots <= 0:
                await interaction.response.send_message(
                    "❌ Party is already full.", ephemeral=True)
                return

            # Add to party
            members.append(uid)
            user_party[uid] = (self.selected_time, self.selected_ch,
                               self.selected_boss, 1)
            await interaction.response.send_message(
                f"✅ {interaction.user.display_name} joined {self.selected_time} "
                f"{self.selected_ch} {self.selected_boss} ({len(members)}/5 players)",
                ephemeral=True)

    # ------------------------------
    # Leave Party
    # ------------------------------
    async def leave_callback(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if uid not in user_party:
            await interaction.response.send_message(
                "⚠️ You are not in any party.", ephemeral=True)
            return

        time, ch, boss, count = user_party[uid]
        members = parties[time][ch][boss]
        key = (time, ch, boss)

        # Remove self
        if uid in members:
            members.remove(uid)

        # Remove friends if any
        friends_count = 0
        if key in party_friend_names and uid in party_friend_names[key]:
            for f in party_friend_names[key][uid]:
                if f in members:
                    members.remove(f)
            friends_count = len(party_friend_names[key][uid])
            del party_friend_names[key][uid]

        del user_party[uid]
        await interaction.response.send_message(
            f"↩️ {interaction.user.display_name} left the party {time} {ch} {boss} "
            f"(released {count} slot(s), including {friends_count} friend(s))",
            ephemeral=True)

    # ------------------------------
    # Check Party
    # ------------------------------
    async def check_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await show_party(interaction)


# ------------------------------
# Friend Modal
# ------------------------------
class FriendModal(discord.ui.Modal, title="Add Party Members"):

    def __init__(self, view_self):
        super().__init__(timeout=300)
        self.view_self = view_self
        self.friend_inputs = []

        # Create input fields based on number of friends
        for i in range(1, self.view_self.selected_count):
            input_field = discord.ui.TextInput(
                label=f"Friend #{i}",
                placeholder="Enter friend's name",
                required=True,
                max_length=50,
            )
            self.add_item(input_field)
            self.friend_inputs.append(input_field)

    async def on_submit(self, interaction: discord.Interaction):
        key = (self.view_self.selected_time, self.view_self.selected_ch,
               self.view_self.selected_boss)
        members = parties[self.view_self.selected_time][
            self.view_self.selected_ch][self.view_self.selected_boss]
        uid = interaction.user.id

        # Check slot again before adding
        remaining_slots = 5 - len(members)
        if remaining_slots < self.view_self.selected_count:
            await interaction.response.send_message(
                f"❌ Only {remaining_slots} slot(s) left. Not enough for {self.view_self.selected_count} players.",
                ephemeral=True)
            return

        # Add members
        members.append(uid)
        friend_names = [f.value for f in self.friend_inputs]
        members.extend(friend_names)

        user_party[uid] = key + (self.view_self.selected_count, )

        if key not in party_friend_names:
            party_friend_names[key] = {}
        party_friend_names[key][uid] = friend_names

        await interaction.response.send_message(
            f"✅ {interaction.user.display_name} joined {self.view_self.selected_time} "
            f"{self.view_self.selected_ch} {self.view_self.selected_boss} "
            f"with: {', '.join(friend_names)} "
            f"({len(members)}/5 players)",
            ephemeral=True)


# ------------------------------
# Slash Command mhjoin
# ------------------------------
@bot.tree.command(
    name="mhjoin",
    description=
    "เข้าปาร์ตี้แบบ UI เลือก เวลา/CH/Boss/จำนวนคน (โพสต์ครั้งเดียวใช้ร่วมกัน)")
async def mhjoin(interaction: discord.Interaction):
    channel = interaction.channel

    # ตรวจสอบโพสต์ซ้ำ
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            for embed in msg.embeds:
                if embed.title and "Party Monster Hunt" in embed.title:
                    await interaction.response.send_message(
                        "❌ This chat already contains a /mhjoin. Duplicate not allowed.",
                        ephemeral=True)
                    return

    embed = discord.Embed(
        title="🎯 Party Monster Hunt",
        description=(
            "ขั้นตอนการจองคิว\n"
            "- เลือกช่วงเวลา ( Time select )\n"
            "- เลือก Channel ( Channel select )\n"
            "- เลือก จุดบอส ( Boss select )\n"
            "- กำหนดจำนวนสมาชิกในปาร์ตี้ ( 1-5 คน )\n"
            "- กรอกข้อมูลครบถ้วนแล้วกดปุ่ม ยืนยัน ( Confirm )\n"
            "- หากต้องการยกเลิกกดปุ่ม ออกจากปาร์ตี้ ( Leave )\n"
            "- เลือกเช็คปาร์ตี้ เพื่อตรวจสอบสมาชิกในแต่ละจุด ( Check Party )"),
        color=0x00b0f4)
    embed.set_image(url="attachment://aosz_elite_sanctum.png")
    embed.set_footer(text="Party Join System | By XeZer 😎")

    file = discord.File("aosz_elite_sanctum.png",
                        filename="aosz_elite_sanctum.png")
    view = JoinView()
    await channel.send(embed=embed, view=view, file=file)

    await interaction.response.send_message(
        "✅ โพสต์ข้อความเข้าปาร์ตี้เรียบร้อย!", ephemeral=True)


# ------------------------------
# Command list
# ------------------------------
@bot.tree.command(name="list", description="ดูรายชื่อปาร์ตี้")
@app_commands.describe(time="ใส่เวลา เช่น 16.00 (ไม่ใส่เพื่อดูทั้งหมด)")
async def list_party(interaction: discord.Interaction, time: str = None):
    await interaction.response.defer(ephemeral=True)
    await show_party(interaction, time)


@bot.tree.command(name="clear", description="ล้างข้อมูลปาร์ตี้ทั้งหมด")
@app_commands.describe(password="รหัส admin")
async def clear(interaction: discord.Interaction, password: str):
    if password != admin_password:
        await interaction.response.send_message("❌ รหัสไม่ถูกต้อง",
                                                ephemeral=True)
        return 

    for t in parties:
        for ch in parties[t]:
            for boss in parties[t][ch]:
                parties[t][ch][boss] = []
    user_party.clear()
    party_friend_names.clear()
    await interaction.response.send_message("🧹 ล้างข้อมูลปาร์ตี้ทั้งหมดแล้ว",
                                            ephemeral=True)
                                        
@bot.tree.command(name="helpme", description="วิธีใช้งานบอทปาร์ตี้")
async def helpme(interaction: discord.Interaction):
    msg = (
        "📖 **วิธีใช้งานบอทปาร์ตี้**\n"
        "`/mhjoin` → เลือก เวลา / Channel / Boss / จำนวนคน\n"
        "`/list [เวลา]` → ดูรายชื่อปาร์ตี้\n"
        "`/clear` → ล้างข้อมูลปาร์ตี้ทั้งหมด\n"
        "`/settime time:<เวลา> password:<รหัส>` → ตั้งเวลาเริ่ม join\n"
        "`/delete password:<รหัส>` → ลบคนในปาร์ตี้ด้วยปุ่มเลือก เวลา/CH/Boss")
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="settime", description="ตั้งเวลาเริ่ม join")
@app_commands.describe(time="ใส่เวลา เช่น 12.00", password="รหัส admin")
async def settime(interaction: discord.Interaction, time: str, password: str):
    global join_start_time
    if password != admin_password:
        await interaction.response.send_message("❌ รหัสไม่ถูกต้อง",
                                                ephemeral=True)
        return
    join_start_time = time
    await interaction.response.send_message(
        f"⏰ ตั้งเวลาเริ่ม join เป็น {time} เรียบร้อย", ephemeral=True)


# ------------------------------
# Delete View (Admin only)
# ------------------------------
# ------------------------------
# DeleteView (ใช้กับ /delete)
# ------------------------------
class DeleteView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.selected_time = None
        self.selected_ch = None
        self.selected_boss = None

        # Time select
        self.time_select = discord.ui.Select(
            placeholder="Select Time to delete",
            options=[discord.SelectOption(label=t) for t in parties.keys()])
        self.time_select.callback = self.time_callback
        self.add_item(self.time_select)

        # Channel select
        self.ch_select = discord.ui.Select(
            placeholder="Select Channel",
            options=[
                discord.SelectOption(label="CH-1"),
                discord.SelectOption(label="CH-2")
            ])
        self.ch_select.callback = self.ch_callback
        self.add_item(self.ch_select)

        # Boss select
        self.boss_select = discord.ui.Select(
            placeholder="Select Boss",
            options=[
                discord.SelectOption(label=boss)
                for boss in ["Sylph", "Undine", "Gnome", "Salamander"]
            ])
        self.boss_select.callback = self.boss_callback
        self.add_item(self.boss_select)

        # Confirm delete button
        confirm_button = discord.ui.Button(label="✅ Confirm Delete",
                                           style=discord.ButtonStyle.danger)
        confirm_button.callback = self.confirm_callback
        self.add_item(confirm_button)

    async def time_callback(self, interaction: discord.Interaction):
        self.selected_time = self.time_select.values[0]
        await interaction.response.defer(ephemeral=True)

    async def ch_callback(self, interaction: discord.Interaction):
        self.selected_ch = self.ch_select.values[0]
        await interaction.response.defer(ephemeral=True)

    async def boss_callback(self, interaction: discord.Interaction):
        self.selected_boss = self.boss_select.values[0]
        await interaction.response.defer(ephemeral=True)

    async def confirm_callback(self, interaction: discord.Interaction):
        if not (self.selected_time and self.selected_ch
                and self.selected_boss):
            await interaction.response.send_message(
                "⚠️ Please select Time / Channel / Boss first.",
                ephemeral=True)
            return

        key = (self.selected_time, self.selected_ch, self.selected_boss)
        members = parties[self.selected_time][self.selected_ch][
            self.selected_boss]

        if not members:
            await interaction.response.send_message(
                f"⚠️ No players found in {self.selected_time} {self.selected_ch} {self.selected_boss}.",
                ephemeral=True)
            return

        # ลบคนจาก user_party
        removed_users = []
        for uid in list(user_party.keys()):
            t, ch, boss, _ = user_party[uid]
            if (t, ch, boss) == key:
                del user_party[uid]
                removed_users.append(uid)

        # ลบเพื่อนใน party_friend_names
        total_removed = len(removed_users)
        if key in party_friend_names:
            for uid, friends in list(party_friend_names[key].items()):
                if uid in removed_users:
                    total_removed += len(friends)
                    del party_friend_names[key][uid]
            if not party_friend_names[key]:
                del party_friend_names[key]

        # เคลียร์ลิสต์สมาชิกหลัก
        parties[self.selected_time][self.selected_ch][self.selected_boss] = []

        await interaction.response.send_message(
            f"🗑️ Cleared party **{self.selected_time} {self.selected_ch} {self.selected_boss}** "
            f"({total_removed} player(s) removed including friends)",
            ephemeral=True)


@bot.tree.command(name="delete",
                  description="ลบคนในปาร์ตี้ด้วยปุ่มเลือก (Admin)")
@app_commands.describe(password="รหัส admin")
async def delete(interaction: discord.Interaction, password: str):
    if password != admin_password:
        await interaction.response.send_message("❌ รหัสไม่ถูกต้อง",
                                                ephemeral=True)
        return
    view = DeleteView()
    await interaction.response.send_message(
        "เลือก เวลา / Channel / Boss แล้วกด ✅ เพื่อลบผู้เล่นทั้งหมด",
        view=view,
        ephemeral=True)


# ------------------------------
# Bot Ready
# ------------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot Online as {bot.user}")
    log_alive.start()


# -------------------
# Task: log "Bot is alive!" ทุก 5 นาที
# -------------------
@tasks.loop(minutes=5)
async def log_alive():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Bot is alive!")


# ------------------------------
# Reaction Role System (เหมือนเดิม)
# ------------------------------
reaction_roles = {
    "<:ln2:1406935643665207337>": {
        "role_name": "ln2",
        "color": 0x1abc9c,
        "desc": "Game Lineage2M"
    },
    "<:roo:1406935556956356739>": {
        "role_name": "roo",
        "color": 0xe67e22,
        "desc": "Game Ragnarok Origin"
    },
    "<:rom:1406935703685824611>": {
        "role_name": "rom",
        "color": 0x9b59b6,
        "desc": "Game Ragnarok Eternal Love"
    },
    "<:stream:1417502619261337712>": {
        "role_name": "livestream",
        "color": 0x9b59b6,
        "desc": "Participants and followers of YouTube live streams"
    }
}
ADMIN_CHANNEL_ID = 1417463299423076373


@bot.tree.command(name="setup_roles",
                  description="Request roles with admin approval")
async def setup_roles(interaction: discord.Interaction):
    """Post main message with emoji buttons for users to request roles."""

    class RoleView(discord.ui.View):

        def __init__(self):
            super().__init__(timeout=None)
            for emoji_str, info in reaction_roles.items():
                emoji_obj = discord.PartialEmoji.from_str(emoji_str)
                button = discord.ui.Button(style=discord.ButtonStyle.secondary,
                                           emoji=emoji_obj)
                button.callback = self.make_callback(info)
                self.add_item(button)

        def make_callback(self, info):
            role_name = info["role_name"]
            role_color = info["color"]

            async def callback(interact: discord.Interaction):
                member = interact.user
                guild = interact.guild
                role_obj = discord.utils.get(guild.roles, name=role_name)

                # Check if member already has the role
                if role_obj in member.roles:
                    await interact.response.send_message(
                        f"⚠️ You already have the role **{role_name}**. Please do not click again.",
                        ephemeral=True)
                    return

                # If not, open modal for input
                class InfoModal(discord.ui.Modal,
                                title=f"{role_name} Request"):
                    character_name = discord.ui.TextInput(
                        label="Character Name",
                        placeholder="Enter your character name",
                        max_length=50)
                    contact = discord.ui.TextInput(
                        label="Contract / Referral",
                        placeholder="Who referred you or contract info",
                        max_length=50)

                    async def on_submit(
                            self, modal_interaction: discord.Interaction):
                        member = modal_interaction.user
                        guild = modal_interaction.guild

                        # Respond to user
                        await modal_interaction.response.send_message(
                            embed=discord.Embed(
                                title="✅ Role Request Submitted!",
                                description=
                                (f"You have requested the role: **{role_name}**\n"
                                 f"Character Name: `{self.character_name.value}`\n"
                                 f"Contract / Referral: `{self.contact.value}`\n\n"
                                 "Please wait for admin approval."),
                                color=role_color),
                            ephemeral=True)

                        # Send to admin channel with Confirm/Reject buttons
                        admin_channel = guild.get_channel(ADMIN_CHANNEL_ID)
                        if not admin_channel:
                            return

                        class AdminView(discord.ui.View):

                            def __init__(self):
                                super().__init__(timeout=None)

                                confirm_button = discord.ui.Button(
                                    label="✅ Confirm Role",
                                    style=discord.ButtonStyle.green)
                                reject_button = discord.ui.Button(
                                    label="❌ Reject",
                                    style=discord.ButtonStyle.red)

                                async def confirm_callback(
                                        btn_interact: discord.Interaction):
                                    if role_obj and guild.me.top_role > role_obj:
                                        await member.add_roles(role_obj)
                                        await btn_interact.response.send_message(
                                            f"✅ {member.display_name} has been granted the role **{role_name}**!",
                                            ephemeral=True)
                                        await btn_interact.message.edit(
                                            view=None)
                                        try:
                                            await member.send(
                                                f"🎉 Your role request **{role_name}** has been approved by admin!"
                                            )
                                        except:
                                            pass
                                    else:
                                        await btn_interact.response.send_message(
                                            "❌ Bot does not have permission to add this role",
                                            ephemeral=True)

                                async def reject_callback(
                                        btn_interact: discord.Interaction):
                                    await btn_interact.response.send_message(
                                        f"❌ Role request of {member.display_name} has been rejected",
                                        ephemeral=True)
                                    await btn_interact.message.edit(view=None)
                                    try:
                                        await member.send(
                                            f"❌ Your role request **{role_name}** was rejected by admin."
                                        )
                                    except:
                                        pass

                                confirm_button.callback = confirm_callback
                                reject_button.callback = reject_callback
                                self.add_item(confirm_button)
                                self.add_item(reject_button)

                        admin_embed = discord.Embed(
                            title=f"📩 Role Request: {role_name}",
                            color=role_color)
                        admin_embed.add_field(name="User",
                                              value=member.mention,
                                              inline=False)
                        admin_embed.add_field(name="Character Name",
                                              value=self.character_name.value,
                                              inline=False)
                        admin_embed.add_field(name="Contract / Referral",
                                              value=self.contact.value,
                                              inline=False)
                        admin_embed.set_footer(
                            text="Admin Panel | Approve or Reject")
                        await admin_channel.send(embed=admin_embed,
                                                 view=AdminView())

                await interact.response.send_modal(InfoModal())

            return callback

    # Main embed message
    main_embed = discord.Embed(
        title="👋 Request Your Role Here!",
        description="Click the emoji buttons below to request a role:\n\n",
        color=0x7289DA)

    for emoji_str, info in reaction_roles.items():
        main_embed.add_field(name=f"{emoji_str} {info['role_name']}",
                             value=info['desc'],
                             inline=False)

    main_embed.set_footer(
        text="Role Request System | Please fill in all information")

    view = RoleView()
    await interaction.response.send_message(embed=main_embed,
                                            view=view,
                                            ephemeral=False)

# ------------------------------
# ตัวแปรหลัก
# ------------------------------
dungeons = {
    "Anima Tower": [],
    "Seaside Ruins": [],
    "Juperos Ruins": []  # ✅ เพิ่มดันใหม่
}
user_status = {}

JOB_OPTIONS = [
    "Rune Knight", "Royal Guard", "Sorcerer", "Warlock", "Guillotine Cross",
    "Shadow Chaser", "Mechanic", "Genetic", "Gand Summoner", "Archbishop",
    "Shura", "Super Novice", "Ranger", "Wanderer", "Nightwatch"
]

STATUS_EMOJI = {"WAIT": "⌛", "DONE": "✅"}


# ------------------------------
# ฟังก์ชันช่วยเหลือ
# ------------------------------
def _find_user_in_dungeon(user_id, dungeon_name):
    data = dungeons.get(dungeon_name, [])
    for i, p in enumerate(data):
        if p.get("user_id") == user_id:
            return i
    return None


def format_queue_table(dungeon_name: str):
    data = dungeons.get(dungeon_name, [])
    if not data:
        return "❌ ไม่มีข้อมูลในคิวตอนนี้"

    rows = []
    for party in data:
        for member in party.get("members", []):
            char_name = member.get("character", "-")

            # ✅ ตรวจสอบชื่อ ถ้ามี pattern 000 - ให้ตัดออก
            if len(char_name) >= 5 and char_name[:3].isdigit(
            ) and char_name[3:5] == " -":
                char_name = char_name[5:]  # ตัดเลขหน้า + " -"

            rows.append({
                "status":
                STATUS_EMOJI.get(member.get("status", "WAIT")),
                "job":
                member.get("job", "-"),
                "character":
                char_name
            })

    if not rows:
        return "❌ ไม่มีข้อมูลในคิวตอนนี้"

    width_no = 4
    width_status = 8
    width_job = 18
    width_char = 16

    header = f"{'No'.ljust(width_no)}| {'Status'.ljust(width_status)}| {'Job'.ljust(width_job)}| {'Character'.ljust(width_char)}"
    separator = "-" * (width_no + width_status + width_job + width_char + 9)

    lines = []
    for i, row in enumerate(rows, start=1):
        line = f"{str(i).ljust(width_no)}| {row['status'].ljust(width_status-1)}| {row['job'].ljust(width_job)}| {row['character'].ljust(width_char)}"
        lines.append(line)

    total_line = f"\nTotal players: {len(rows)}"
    now = datetime.now(timezone(
        timedelta(hours=7))).strftime("%d %b %Y, %H:%M")
    last_update = f"Last updated: {now}"

    table = "```" + "\n".join([header, separator, *lines
                               ]) + "```" + total_line + f"\n{last_update}"
    return table


# ------------------------------
# Party View
# ------------------------------
class PartyView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.user_data = {}

        # Dropdown Dungeon ✅ เพิ่ม Juperos Ruins
        self.dungeon_select = discord.ui.Select(
            placeholder="Select Dungeon",
            options=[
                discord.SelectOption(label="Anima Tower", value="Anima Tower"),
                discord.SelectOption(label="Seaside Ruins",
                                     value="Seaside Ruins"),
                discord.SelectOption(label="Juperos Ruins",
                                     value="Juperos Ruins"),  # ✅
            ],
        )
        self.dungeon_select.callback = self.on_dungeon_select
        self.add_item(self.dungeon_select)

        # Dropdown Job
        self.job_select = discord.ui.Select(
            placeholder="Select Job",
            options=[discord.SelectOption(label=j) for j in JOB_OPTIONS],
        )
        self.job_select.callback = self.on_job_select
        self.add_item(self.job_select)

        # Buttons
        self.join_btn = discord.ui.Button(label="Confirm",
                                          style=discord.ButtonStyle.green)
        self.join_btn.callback = self.on_join
        self.add_item(self.join_btn)

        self.cancel_btn = discord.ui.Button(label="Leave",
                                            style=discord.ButtonStyle.red)
        self.cancel_btn.callback = self.on_cancel
        self.add_item(self.cancel_btn)

        self.done_btn = discord.ui.Button(label="Done",
                                          style=discord.ButtonStyle.blurple)
        self.done_btn.callback = self.on_done
        self.add_item(self.done_btn)

        self.check_queue_btn = discord.ui.Button(
            label="Check Queue", style=discord.ButtonStyle.gray)
        self.check_queue_btn.callback = self.on_check_queue
        self.add_item(self.check_queue_btn)

    # --------------------------
    # Dropdown Dungeon
    # --------------------------
    async def on_dungeon_select(self, interaction: discord.Interaction):
        uid = interaction.user.id
        dungeon = self.dungeon_select.values[0]
        self.user_data[uid] = self.user_data.get(uid, {})
        self.user_data[uid]["dungeon"] = dungeon
        await interaction.response.defer(ephemeral=True)

    # --------------------------
    # Dropdown Job
    # --------------------------
    async def on_job_select(self, interaction: discord.Interaction):
        uid = interaction.user.id
        job = self.job_select.values[0]
        self.user_data[uid] = self.user_data.get(uid, {})
        self.user_data[uid]["job"] = job
        await interaction.response.defer(ephemeral=True)

    # --------------------------
    # JOIN
    # --------------------------
    async def on_join(self, interaction: discord.Interaction):
        uid = interaction.user.id
        data = self.user_data.get(uid)
        if not data or "dungeon" not in data or "job" not in data:
            await interaction.response.send_message(
                "⚠️ Please select both Dungeon and Job first", ephemeral=True)
            return

        dungeon = data["dungeon"]
        job = data["job"]
        name = interaction.user.display_name

        if _find_user_in_dungeon(uid, dungeon) is not None:
            await interaction.response.send_message(
                f"⚠️ You already joined {dungeon}", ephemeral=True)
            return

        entry = {
            "user_id": uid,
            "members": [{
                "character": name,
                "job": job,
                "status": "WAIT"
            }],
            "status": "WAIT",
        }
        dungeons[dungeon].append(entry)
        user_status[uid] = {"dungeon": dungeon, "status": "WAIT"}

        await interaction.response.send_message(
            f"✅ Joined {dungeon} — Job: {job}", ephemeral=True)

    # --------------------------
    # CANCEL
    # --------------------------
    async def on_cancel(self, interaction: discord.Interaction):
        uid = interaction.user.id
        data = self.user_data.get(uid)
        if not data or "dungeon" not in data:
            await interaction.response.send_message("⚠️ Select dungeon first",
                                                    ephemeral=True)
            return

        dungeon = data["dungeon"]
        idx = _find_user_in_dungeon(uid, dungeon)
        if idx is None:
            await interaction.response.send_message(
                f"⚠️ You have not joined {dungeon}", ephemeral=True)
            return

        dungeons[dungeon].pop(idx)
        user_status.pop(uid, None)
        await interaction.response.send_message(
            f"❌ Cancelled queue in {dungeon}", ephemeral=True)

    # --------------------------
    # DONE
    # --------------------------
    async def on_done(self, interaction: discord.Interaction):
        uid = interaction.user.id
        data = self.user_data.get(uid)
        if not data or "dungeon" not in data:
            await interaction.response.send_message("⚠️ Select dungeon first",
                                                    ephemeral=True)
            return

        dungeon = data["dungeon"]
        idx = _find_user_in_dungeon(uid, dungeon)
        if idx is None:
            await interaction.response.send_message(
                f"⚠️ You have not joined {dungeon}", ephemeral=True)
            return

        party = dungeons[dungeon][idx]
        party["status"] = "DONE"
        for m in party.get("members", []):
            m["status"] = "DONE"
        user_status.setdefault(uid, {})["status"] = "DONE"
        await interaction.response.send_message(
            f"🏁 Status for {dungeon} updated to DONE", ephemeral=True)

    # --------------------------
    # Check Queue
    # --------------------------
    async def on_check_queue(self, interaction: discord.Interaction):
        uid = interaction.user.id
        data = self.user_data.get(uid)

        if not data or "dungeon" not in data:
            await interaction.response.send_message(
                "⚠️ Please select a Dungeon first", ephemeral=True)
            return

        dungeon = data["dungeon"]

        if dungeon == "Anima Tower":
            embed = discord.Embed(
                title="🗺️ Anima Tower Queue",
                description=format_queue_table("Anima Tower"),
                color=0x1abc9c,
            )
        elif dungeon == "Seaside Ruins":
            embed = discord.Embed(
                title="🌊 Seaside Ruins Queue",
                description=format_queue_table("Seaside Ruins"),
                color=0x3498db,
            )
        elif dungeon == "Juperos Ruins":  # ✅ เพิ่ม embed ของ Juperos Ruins
            embed = discord.Embed(
                title="⚙️ Juperos Ruins Queue",
                description=format_queue_table("Juperos Ruins"),
                color=0xe67e22,
            )
        else:
            await interaction.response.send_message(
                "⚠️ Unknown dungeon selected", ephemeral=True)
            return

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ------------------------------
# /party_system command
# ------------------------------
@bot.tree.command(name="party_system",
                  description="Open Dungeon & Job selector")
async def party_system_cmd(interaction: discord.Interaction):
    channel = interaction.channel
    # ตรวจสอบโพสต์ซ้ำ
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            for embed in msg.embeds:
                if embed.title and "Dungeon & Job Party System" in embed.title:
                    await interaction.response.send_message(
                        "❌ This chat already contains a /party_system. Duplicate not allowed.",
                        ephemeral=True)
                    return
    embed = discord.Embed(
        title="🎯 Dungeon & Job Party System",
        description=(
            "**Queue Booking Steps:**\n"
            "- Select a dungeon\n"
            "- Select your job\n"
            "- Confirm: After selecting Dungeon and Job,join the queue\n"
            "- Leave: Select your dungeon and cancel your queue\n"
            "- Done: Select your dungeon and mark your queue as completed\n"
            "- Check Queue: Select your dungeon and view the current queue"),
        color=0x9b59b6,
    )
    embed.set_image(url="attachment://aosz_party_system.jpg")

    file = discord.File("aosz_party_system.jpg",
                        filename="aosz_party_system.jpg")

    view = PartyView()
    await interaction.response.send_message(embed=embed,
                                            view=view,
                                            file=file,
                                            ephemeral=False)


# ------------------------------
# /clearqueue command
# ------------------------------
@bot.tree.command(name="clearqueue",
                  description="Clear all queues for all dungeons")
@app_commands.describe(password="รหัส admin")
async def clearqueue_cmd(interaction: discord.Interaction, password: str):
    if password != admin_password:
        await interaction.response.send_message("❌ รหัสไม่ถูกต้อง",
                                                ephemeral=True)
        return
    # ล้างข้อมูลของทุกดัน
    for dungeon in dungeons.keys():
        dungeons[dungeon].clear()

    # ล้าง user_status ทั้งหมด
    user_status.clear()

    await interaction.response.send_message(
        "🗑️ All queues for Anima Tower, Seaside Ruins, and Juperos Ruins have been cleared.",
        ephemeral=True)


# ------------------------------
# /listqueue command
# ------------------------------
@bot.tree.command(name="listqueue",
                  description="Show current queues for all dungeons")
async def listqueue_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Current Queues for All Dungeons",
        color=0x9b59b6,
    )

    # เพิ่มข้อมูลของแต่ละดัน
    for dungeon, color, emoji in [
        ("Anima Tower", 0x1abc9c, "🗺️"),
        ("Seaside Ruins", 0x3498db, "🌊"),
        ("Juperos Ruins", 0xe67e22, "⚙️"),
    ]:
        table = format_queue_table(dungeon)
        embed.add_field(name=f"{emoji} {dungeon}", value=table, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

# เรียก keep_alive ก่อนรันบอท
keep_alive()
bot.run(os.environ["DISCORD_BOT_TOKEN"])
