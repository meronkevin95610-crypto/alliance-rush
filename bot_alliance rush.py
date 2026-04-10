import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import threading
from flask import Flask
from dotenv import load_dotenv

# --- CONFIGURATION & DATA ---
load_dotenv() 
app = Flask('')
DATA_FILE = "stats_rush_event.json"
CONFIG_FILE = "config_rush.json"

# Récupération du Token depuis l'environnement Render
TOKEN = os.getenv("DISCORD_TOKEN")

# IDs des Salons
DASHBOARD_CHANNEL_ID = 1473418141160837140
CH_ATTAQUE = 1470492327679230156
CH_DEFENSE = 1470492446885544059

ALLIANCE_GUILDES = [
    "OLYMPE", "EXODE", "LACOSTE TN", "THE UNKNOWNS", "GUCCI MOB",
    "OLD SCHOOL", "NONOOB", "STELLAR" 
]

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding='utf-8') as f: return json.load(f)
        except: return {"users": {}}
    return {"users": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_config():
    default = {"bareme": {"Prisme": {"4v4": 15, "4v3/2": 10, "4v1/0": 7, "perdu_long": 1},
                         "Perco_Atk": {"4v4": 3, "4v3/2": 2, "4v1/0": 1},
                         "Perco_Def": {"win": 2}, "bonus_mixte": 1, "bonus_long": 1}}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding='utf-8') as f: return json.load(f)
        except: return default
    return default

def save_config(config):
    with open(CONFIG_FILE, "w", encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# --- ADMINISTRATION (MODAL & PANEL) ---

class PtsInputModal(discord.ui.Modal, title="Modifier Points"):
    val = discord.ui.TextInput(label="Nouvelle valeur", placeholder="Ex: 5")
    def __init__(self, cat, key):
        super().__init__()
        self.cat, self.key = cat, key

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = float(self.val.value)
            cfg = load_config()
            if self.cat in ["bonus_mixte", "bonus_long"]: cfg["bareme"][self.cat] = v
            else: cfg["bareme"][self.cat][self.key] = v
            save_config(cfg)
            await interaction.response.send_message(f"✅ Barème mis à jour : `{self.cat}` -> `{v} pts`", ephemeral=True)
        except: await interaction.response.send_message("❌ Erreur de nombre.", ephemeral=True)

class ConfigPanel(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="💎 Prismes", style=discord.ButtonStyle.primary)
    async def b_prisme(self, interaction, button):
        v = discord.ui.View()
        for k in ["4v4", "4v3/2", "4v1/0", "perdu_long"]:
            btn = discord.ui.Button(label=f"Prisme {k}")
            def mk_cb(key):
                async def cb(i): await i.response.send_modal(PtsInputModal("Prisme", key))
                return cb
            btn.callback = mk_cb(k); v.add_item(btn)
        await interaction.response.send_message("Points Prismes :", view=v, ephemeral=True)

    @discord.ui.button(label="⚔️ Percos", style=discord.ButtonStyle.secondary)
    async def b_perco(self, interaction, button):
        v = discord.ui.View()
        for k in ["4v4", "4v3/2", "4v1/0"]:
            btn = discord.ui.Button(label=f"Atk {k}")
            def mk_cb(key):
                async def cb(i): await i.response.send_modal(PtsInputModal("Perco_Atk", key))
                return cb
            btn.callback = mk_cb(k); v.add_item(btn)
        bd = discord.ui.Button(label="Def Win", style=discord.ButtonStyle.success)
        bd.callback = lambda i: i.response.send_modal(PtsInputModal("Perco_Def", "win"))
        v.add_item(bd)
        await interaction.response.send_message("Points Percos :", view=v, ephemeral=True)

class ResetConfirmView(discord.ui.View):
    def __init__(self): super().__init__(timeout=30)
    @discord.ui.button(label="CONFIRMER LE RESET", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        save_data({"users": {}})
        await interaction.response.edit_message(content="✅ **Reset terminé !**", view=None)

# --- FONCTIONS CLASSEMENT ---
def build_player_rank(guild, data):
    emb = discord.Embed(title="🏆 CLASSEMENT INDIVIDUEL", color=0xedb21c)
    scores = data.get("users", {})
    if not scores:
        emb.description = "Aucune donnée."
        return emb
    sorted_u = sorted(scores.items(), key=lambda x: x[1].get('pts_perco', 0), reverse=True)[:15]
    table = "```\n# Joueur        | Pts  | W | L | %\n" + "-"*37 + "\n"
    for uid, d in sorted_u:
        name = d.get("name", "Inconnu")[:12].ljust(13)
        pts = d.get('pts_perco', 0.0); w, l = d.get('wins', 0), d.get('losses', 0)
        ratio = (w / (w+l) * 100) if (w+l) > 0 else 0
        table += f"{name} | {pts:>4.1f} | {w:>1} | {l:>1} | {ratio:>3.0f}%\n"
    emb.description = table + "```"
    return emb

def build_guild_rank(data):
    emb = discord.Embed(title="🏰 CLASSEMENT PAR GUILDE", color=0x3498db)
    scores = data.get("users", {})
    g_stats = {g: 0.0 for g in ALLIANCE_GUILDES}
    for d in scores.values():
        gn = d.get("guilde", "").upper()
        if gn in g_stats: g_stats[gn] += d.get("pts_perco", 0.0)
    sorted_g = sorted(g_stats.items(), key=lambda x: x[1], reverse=True)
    table = "```\nPos | Guilde            | Total Pts\n" + "-"*32 + "\n"
    for i, (n, p) in enumerate(sorted_g, 1):
        table += f"{i:<3} | {n:<17} | {p:>6.1f}\n"
    emb.description = table + "```"
    return emb

# --- WIZARD DE COMBAT ---
class MemberSelect(discord.ui.UserSelect):
    def __init__(self): super().__init__(placeholder="Participants (max 4)", min_values=1, max_values=4)
    async def callback(self, interaction): await self.view.check_guilds(interaction, self.values)

class CombatWizard(discord.ui.View):
    def __init__(self, user, bot_instance):
        super().__init__(timeout=600)
        self.user, self.bot = user, bot_instance
        self.participants = []
        self.type_combat = self.format = self.issue = None
        self.mixte = self.long_combat = False
        self.pending_members = []
        
        for l, v in [("💎 Prisme", "Prisme"), ("⚔️ Perco Atk", "Perco_Atk"), ("🛡️ Perco Def", "Perco_Def")]:
            btn = discord.ui.Button(label=l, style=discord.ButtonStyle.primary)
            def mk_cb(val):
                async def cb(i): self.type_combat = val; await self.ask_members(i)
                return cb
            btn.callback = mk_cb(v); self.add_item(btn)

    async def ask_members(self, interaction):
        self.clear_items(); self.add_item(MemberSelect())
        await interaction.response.edit_message(content="**Étape 2 :** Qui a combattu ?", view=self)

    async def check_guilds(self, interaction, members):
        self.participants = members; data = load_data()
        self.pending_members = [m for m in members if str(m.id) not in data["users"] or data["users"][str(m.id)]["guilde"] == "À Définir"]
        if self.pending_members: await self.ask_next_guild_config(interaction)
        else: await self.proceed_to_format(interaction)

    async def ask_next_guild_config(self, interaction):
        if not self.pending_members: await self.proceed_to_format(interaction); return
        curr = self.pending_members[0]; self.clear_items()
        sel = discord.ui.Select(placeholder=f"Guilde de {curr.display_name} ?", options=[discord.SelectOption(label=g) for g in ALLIANCE_GUILDES])
        async def guild_cb(i):
            d = load_data(); uid = str(curr.id)
            if uid not in d["users"]: d["users"][uid] = {"name": curr.display_name, "guilde": sel.values[0], "pts_perco": 0.0, "wins": 0, "losses": 0}
            else: d["users"][uid]["guilde"] = sel.values[0]
            save_data(d); self.pending_members.pop(0); await self.ask_next_guild_config(i)
        sel.callback = guild_cb; self.add_item(sel)
        await interaction.response.edit_message(content=f"⚙️ Guilde de **{curr.display_name}** ?", view=self)

    async def proceed_to_format(self, interaction):
        if self.type_combat == "Perco_Def": self.format = "4v4"; await self.show_issue(interaction)
        else:
            self.clear_items()
            for f_l, f_v in [("4v4 Full", "4v4"), ("4v3/2", "4v3/2"), ("4v1/0", "4v1/0")]:
                btn = discord.ui.Button(label=f_l, style=discord.ButtonStyle.secondary)
                def mk_cb(v):
                    async def cb(it): self.format = v; await self.show_issue(it)
                    return cb
                btn.callback = mk_cb(f_v); self.add_item(btn)
            await interaction.response.edit_message(content="**Étape 3 :** Format adverse ?", view=self)

    async def show_issue(self, i):
        self.clear_items()
        for res in ["Victoire", "Défaite"]:
            btn = discord.ui.Button(label=res, style=discord.ButtonStyle.success if res=="Victoire" else discord.ButtonStyle.danger)
            def mk_cb(r):
                async def cb(it): self.issue = r; await self.show_bonus(it)
                return cb
            btn.callback = mk_cb(res); self.add_item(btn)
        await i.response.edit_message(content="**Étape 4 :** Résultat ?", view=self)

    async def show_bonus(self, i):
        self.clear_items()
        bm = discord.ui.Button(label="Team Mixte ✅" if self.mixte else "Team Mixte ?", style=discord.ButtonStyle.blurple)
        async def cbm(it): self.mixte = not self.mixte; await self.show_bonus(it)
        bm.callback = cbm
        bl = discord.ui.Button(label="Combat Long ✅" if self.long_combat else "Combat Long ?", style=discord.ButtonStyle.blurple)
        async def cbl(it): self.long_combat = not self.long_combat; await self.show_bonus(it)
        bl.callback = cbl
        vf = discord.ui.Button(label="VALIDER", style=discord.ButtonStyle.green, row=1)
        vf.callback = self.finish
        self.add_item(bm); self.add_item(bl); self.add_item(vf)
        await i.response.edit_message(content="**Étape 5 :** Bonus ?", view=self)

    async def finish(self, interaction):
        cfg = load_config()["bareme"]; pts = 0.0; win = (self.issue == "Victoire")
        if self.type_combat == "Prisme":
            if win: pts = float(cfg["Prisme"].get(self.format, 7))
            elif self.format == "4v4" and self.long_combat: pts = float(cfg["Prisme"].get("perdu_long", 1))
        elif self.type_combat == "Perco_Atk" and win: pts = float(cfg["Perco_Atk"].get(self.format, 1))
        elif self.type_combat == "Perco_Def" and win: pts = float(cfg["Perco_Def"].get("win", 2))
        if self.mixte: pts += float(cfg.get("bonus_mixte", 1))
        if self.long_combat and win: pts += float(cfg.get("bonus_long", 1))
        
        target_ch = self.bot.get_channel(CH_DEFENSE if self.type_combat == "Perco_Def" else CH_ATTAQUE)
        await interaction.response.edit_message(content=f"🏁 **{pts} pts/joueur.** Envoie le SCREEN !", view=None)
        try:
            msg = await self.bot.wait_for("message", check=lambda m: m.author == self.user and m.attachments, timeout=300)
            data = load_data(); summary = ""
            for m in self.participants:
                uid = str(m.id); data["users"][uid]["pts_perco"] += pts
                if win: data["users"][uid]["wins"] += 1
                else: data["users"][uid]["losses"] += 1
                summary += f"• {m.display_name} ({data['users'][uid]['guilde']})\n"
            save_data(data)
            if target_ch: await target_ch.send(f"✅ **{self.type_combat}** ({pts} pts)\n{summary}")
            await msg.reply("✅ Enregistré !")
        except: pass

# --- SETUP BOT ---
class RushBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self): self.update_dashboard.start(); await self.tree.sync()

    @tasks.loop(minutes=5)
    async def update_dashboard(self):
        ch = self.get_channel(DASHBOARD_CHANNEL_ID)
        if ch:
            data = load_data(); await ch.purge(limit=5, check=lambda m: m.author == self.user)
            await ch.send(embed=build_player_rank(ch.guild, data))
            await ch.send(embed=build_guild_rank(data))

bot = RushBot()

@bot.tree.command(name="ajouter_combat", description="Lancer le wizard de combat")
async def add(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send("**Étape 1 :** Quel type de combat ?", view=CombatWizard(interaction.user, bot))

@bot.tree.command(name="classement", description="Voir le classement actuel")
async def classement(interaction: discord.Interaction):
    data = load_data()
    await interaction.response.send_message(embeds=[build_player_rank(interaction.guild, data), build_guild_rank(data)])

@bot.tree.command(name="admin_panel", description="Gérer les points du barème")
@app_commands.checks.has_permissions(administrator=True)
async def admin(interaction: discord.Interaction):
    await interaction.response.send_message("⚙️ **CONFIGURATION**", view=ConfigPanel(), ephemeral=True)

@bot.tree.command(name="reset_classement", description="Remise à zéro complète")
@app_commands.checks.has_permissions(administrator=True)
async def reset(interaction: discord.Interaction):
    await interaction.response.send_message("🚨 **Reset ?**", view=ResetConfirmView(), ephemeral=True)

@app.route('/')
def home(): return "Bot en ligne !"

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000), daemon=True).start()
    if not TOKEN:
        print("❌ Erreur : DISCORD_TOKEN non trouvé dans l'environnement !")
    else:
        bot.run(TOKEN)
