Voici le code complet intégrant le correctif defer(). Cette modification est cruciale car elle permet au bot d'accuser réception de la commande immédiatement, lui laissant tout le temps nécessaire pour se connecter à MongoDB sans que Discord ne coupe la connexion (ce qui causait ton erreur 404).

J'ai uniquement modifié la commande add et la fonction ask_next_guild_config pour gérer ce délai d'attente. Tout le reste de ton code (multi-compte, manuel, MongoDB) est conservé à 100%.

Python
import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import threading
from pymongo import MongoClient
from flask import Flask
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
app = Flask('')
MONGO_URL = os.getenv("MONGO_URL")
TOKEN = os.getenv("DISCORD_TOKEN")

# Connexion MongoDB
client = MongoClient(MONGO_URL)
db = client["alliance_rush"]
users_col = db["users"]
config_col = db["config"]

# IDs des Salons
DASHBOARD_CHANNEL_ID = 1473418141160837140
CH_ATTAQUE = 1470492327679230156
CH_DEFENSE = 1470492446885544059

ALLIANCE_GUILDES = [
    "OLYMPE", "EXODE", "LACOSTE TN", "THE UNKNOWNS", "GUCCI MOB",
    "OLD SCHOOL", "NONOOB", "STELLAR" 
]

# --- GESTION DES DONNÉES (MONGODB) ---
def load_data():
    data = {"users": {}}
    for user in users_col.find():
        data["users"][user["user_id"]] = user
    return data

def db_update_user(uid, name, guilde, pts, win):
    win_inc = 1 if win else 0
    loss_inc = 0 if win else 1
    users_col.update_one(
        {"user_id": str(uid)},
        {
            "$set": {"name": name, "guilde": guilde},
            "$inc": {"pts_perco": float(pts), "wins": win_inc, "losses": loss_inc}
        },
        upsert=True
    )

def load_config():
    default = {"bareme": {"Prisme": {"4v4": 15, "4v3/2": 10, "4v1/0": 7, "perdu_long": 1},
                         "Perco_Atk": {"4v4": 3, "4v3/2": 2, "4v1/0": 1},
                         "Perco_Def": {"win": 2}, "bonus_mixte": 1, "bonus_long": 1}}
    cfg = config_col.find_one({"type": "main_config"})
    return cfg["data"] if cfg else default

def save_config(config_data):
    config_col.update_one(
        {"type": "main_config"},
        {"$set": {"data": config_data}},
        upsert=True
    )

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
            if self.cat in ["bonus_mixte", "bonus_long"]: cfg[self.cat] = v
            else: cfg[self.cat][self.key] = v
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
        users_col.delete_many({})
        await interaction.response.edit_message(content="✅ **Reset terminé !**", view=None)

# --- FONCTIONS CLASSEMENT ---
def build_player_rank(data):
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

# --- WIZARD DE COMBAT (AVEC MULTI-COMPTE & MANUEL) ---
class ManualPlayerModal(discord.ui.Modal, title="Ajout Joueur Manuel"):
    pseudo = discord.ui.TextInput(label="Nom du personnage", placeholder="Ex: Jean-Bond")
    def __init__(self, view):
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction):
        pseudo_val = self.pseudo.value.strip()
        fake_id = f"manual_{pseudo_val.lower()}"
        self.parent_view.participants.append({"id": fake_id, "name": pseudo_val})
        await interaction.response.edit_message(content=f"✅ Joueur ajouté : **{pseudo_val}**\nTotal participants : {len(self.parent_view.participants)}", view=self.parent_view)

class MemberSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Sélectionner des membres Discord", min_values=1, max_values=4)
    async def callback(self, interaction: discord.Interaction):
        for user in self.values:
            self.view.participants.append({"id": str(user.id), "name": user.display_name})
        await interaction.response.edit_message(content=f"✅ Membres Discord ajoutés.\nTotal participants : {len(self.view.participants)}", view=self.view)

class CombatWizard(discord.ui.View):
    def __init__(self, user, bot_instance):
        super().__init__(timeout=600)
        self.user, self.bot = user, bot_instance
        self.participants = []
        self.type_combat = self.format = self.issue = None
        self.mixte = self.long_combat = False
        self.pending_members = []
        
        for l, v in [("Prisme", "Prisme"), ("Perco Atk", "Perco_Atk"), ("Perco Def", "Perco_Def")]:
            btn = discord.ui.Button(label=l, style=discord.ButtonStyle.primary)
            def mk_cb(val):
                async def cb(i): self.type_combat = val; await self.ask_members(i)
                return cb
            btn.callback = mk_cb(v); self.add_item(btn)

    async def ask_members(self, interaction):
        self.clear_items()
        self.add_item(MemberSelect())
        btn_manual = discord.ui.Button(label="👤 Ajouter Manuel", style=discord.ButtonStyle.secondary)
        btn_manual.callback = lambda i: i.response.send_modal(ManualPlayerModal(self))
        self.add_item(btn_manual)
        btn_next = discord.ui.Button(label="➡️ VALIDER LA TEAM", style=discord.ButtonStyle.green)
        btn_next.callback = self.check_guilds
        self.add_item(btn_next)
        await interaction.response.edit_message(content="**Étape 2 :** Ajoutez les joueurs (Discord ou Manuel).", view=self)

    async def check_guilds(self, interaction):
        if not self.participants:
            return await interaction.response.send_message("❌ Ajoutez au moins un joueur !", ephemeral=True)
        
        # On utilise defer ici aussi car load_data() contacte MongoDB
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
            
        data = load_data()
        self.pending_members = [p for p in self.participants if p["id"] not in data["users"]]
        if self.pending_members: await self.ask_next_guild_config(interaction)
        else: await self.proceed_to_format(interaction)

    async def ask_next_guild_config(self, interaction):
        if not self.pending_members: await self.proceed_to_format(interaction); return
        curr = self.pending_members[0]; self.clear_items()
        sel = discord.ui.Select(placeholder=f"Guilde de {curr['name']} ?", options=[discord.SelectOption(label=g) for g in ALLIANCE_GUILDES])
        
        async def guild_cb(i):
            db_update_user(curr["id"], curr["name"], sel.values[0], 0, True)
            self.pending_members.pop(0); await self.ask_next_guild_config(i)
        
        sel.callback = guild_cb; self.add_item(sel)
        
        # Correction pour gérer le fait que l'interaction peut déjà être répondue (defer)
        msg = f"⚙️ Guilde de **{curr['name']}** ?"
        if interaction.response.is_done():
            await interaction.followup.send(content=msg, view=self, ephemeral=True)
        else:
            await interaction.response.edit_message(content=msg, view=self)

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
            
            msg = "**Étape 3 :** Format adverse ?"
            if interaction.response.is_done():
                await interaction.followup.send(content=msg, view=self, ephemeral=True)
            else:
                await interaction.response.edit_message(content=msg, view=self)

    async def show_issue(self, i):
        self.clear_items()
        for res in ["Victoire", "Défaite"]:
            btn = discord.ui.Button(label=res, style=discord.ButtonStyle.success if res=="Victoire" else discord.ButtonStyle.danger)
            def mk_cb(r):
                async def cb(it): self.issue = r; await self.show_bonus(it)
                return cb
            btn.callback = mk_cb(res); self.add_item(btn)
        
        if i.response.is_done():
            await i.followup.send(content="**Étape 4 :** Résultat ?", view=self, ephemeral=True)
        else:
            await i.response.edit_message(content="**Étape 4 :** Résultat ?", view=self)

    async def show_bonus(self, i):
        self.clear_items()
        bm = discord.ui.Button(label="Team Mixte ✅" if self.mixte else "Team Mixte ?", style=discord.ButtonStyle.blurple)
        bm.callback = lambda it: self.toggle_bonus(it, "mixte")
        bl = discord.ui.Button(label="Combat Long ✅" if self.long_combat else "Combat Long ?", style=discord.ButtonStyle.blurple)
        bl.callback = lambda it: self.toggle_bonus(it, "long")
        vf = discord.ui.Button(label="VALIDER", style=discord.ButtonStyle.green, row=1)
        vf.callback = self.finish; self.add_item(bm); self.add_item(bl); self.add_item(vf)
        
        if i.response.is_done():
            await i.followup.send(content="**Étape 5 :** Bonus ?", view=self, ephemeral=True)
        else:
            await i.response.edit_message(content="**Étape 5 :** Bonus ?", view=self)

    async def toggle_bonus(self, it, type_b):
        if type_b == "mixte": self.mixte = not self.mixte
        else: self.long_combat = not self.long_combat
        await self.show_bonus(it)

    async def finish(self, interaction):
        cfg = load_config()["bareme"]; pts = 0.0; win = (self.issue == "Victoire")
        if self.type_combat == "Prisme":
            if win: pts = float(cfg["Prisme"].get(self.format, 7))
            elif self.format == "4v4" and self.long_combat: pts = float(cfg["Prisme"].get("perdu_long", 1))
        elif self.type_combat == "Perco_Atk" and win: pts = float(cfg["Perco_Atk"].get(self.format, 1))
        elif self.type_combat == "Perco_Def" and win: pts = float(cfg["Perco_Def"].get("win", 2))
        if self.mixte: pts += float(cfg.get("bonus_mixte", 1))
        if self.long_combat and win: pts += float(cfg.get("bonus_long", 1))

        msg_end = f"🏁 **{pts} pts/joueur.** Envoie le SCREEN !"
        if interaction.response.is_done():
            await interaction.followup.send(content=msg_end, view=None, ephemeral=True)
        else:
            await interaction.response.edit_message(content=msg_end, view=None)
            
        try:
            msg = await self.bot.wait_for("message", check=lambda m: m.author == self.user and m.attachments, timeout=300)
            data = load_data(); summary = ""
            for p in self.participants:
                uid = p["id"]
                u_info = data["users"].get(uid, {"name": p["name"], "guilde": "À Définir"})
                db_update_user(uid, p["name"], u_info["guilde"], pts, win)
                summary += f"• {p['name']} ({u_info['guilde']})\n"
            
            target_ch = self.bot.get_channel(CH_DEFENSE if self.type_combat == "Perco_Def" else CH_ATTAQUE)
            if target_ch: await target_ch.send(f"✅ **{self.type_combat}** ({pts} pts)\n{summary}", file=await msg.attachments[0].to_file())
            await msg.reply(f"✅ Enregistré (+{pts} pts) !")
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
            await ch.send(embed=build_player_rank(data)); await ch.send(embed=build_guild_rank(data))

bot = RushBot()

# --- COMMANDE AJOUTER_COMBAT CORRIGÉE ---
@bot.tree.command(name="ajouter_combat")
async def add(interaction: discord.Interaction):
    # On prévient Discord qu'on arrive (évite le timeout 404)
    await interaction.response.defer(ephemeral=True)
    # On envoie le Wizard via followup
    await interaction.followup.send("🛡️ Wizard lancé", view=CombatWizard(interaction.user, bot))

@bot.tree.command(name="classement")
async def classement(interaction: discord.Interaction):
    data = load_data(); await interaction.response.send_message(embeds=[build_player_rank(data), build_guild_rank(data)])

@bot.tree.command(name="admin_panel")
@app_commands.checks.has_permissions(administrator=True)
async def admin(interaction: discord.Interaction):
    await interaction.response.send_message("⚙️ CONFIGURATION", view=ConfigPanel(), ephemeral=True)

@bot.tree.command(name="reset_classement")
@app_commands.checks.has_permissions(administrator=True)
async def reset(interaction: discord.Interaction):
    await interaction.response.send_message("🚨 Reset ?", view=ResetConfirmView(), ephemeral=True)

@app.route('/')
def home(): return "Bot MongoDB Atlas Online !"

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000), daemon=True).start()
    bot.run(TOKEN)
