import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import threading
from flask import Flask

# --- CONFIGURATION DU SERVEUR WEB ---
app = Flask('')

@app.route('/')
def home():
    return "Le bot Alliance est opérationnel !"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURATION DU BOT ---
TOKEN = os.environ.get("DISCORD_TOKEN")
DATA_FILE = "stats_rush_event.json"
DASHBOARD_CHANNEL_ID = 1473418141160837140 

ALLIANCE_GUILDES = [
    "OLYMPE", "EXODE", "LACOSTE TN", "THE UNKNOWNS", "GUCCI MOB",
    "OLD SCHOOL", "NONOOB", "STELLAR" 
]

# --- GESTION DES DONNÉES ---
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding='utf-8') as f:
                content = json.load(f)
                if "guildes" not in content: content["guildes"] = {}
                if "users" not in content: content["users"] = {}
                return content
        except Exception:
            return {"users": {}, "guildes": {}}
    return {"users": {}, "guildes": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def generate_leaderboard_embed(data, title="📊 CLASSEMENT RUSH ALLIANCE"):
    embed = discord.Embed(title=title, color=0x2ecc71)
    
    # Section Guildes (Priorité selon ta demande)
    if data.get("guildes"):
        sorted_g = sorted(data["guildes"].items(), key=lambda x: x[1], reverse=True)
        table_g = "```\nPos | Nom de Guilde   | Pts\n" + "-"*28 + "\n"
        for i, (name, pts) in enumerate(sorted_g, 1):
            table_g += f"{i:<3} | {name:<15} | {pts}\n"
        table_g += "```"
        embed.add_field(name="🏰 CLASSEMENT DES GUILDES", value=table_g, inline=False)

    # Section Joueurs
    if data["users"]:
        sorted_u = sorted(data["users"].items(), key=lambda x: x[1]["pts"], reverse=True)
        table_u = "```\nPos | Joueur (Guilde) | Pts | W/L\n" + "-"*32 + "\n"
        for i, (uid, s) in enumerate(sorted_u[:15], 1):
            name = s['name'][:10]
            guilde = s['guilde'][:5]
            table_u += f"{i:<3} | {name:<10} ({guilde:<5}) | {s['pts']:<3} | {s['w']}/{s['l']}\n"
        table_u += "```"
        embed.add_field(name="👤 TOP JOUEURS", value=table_u, inline=False)
    
    return embed

# --- INTERFACES UI (VIEWS) ---

class GuildePointsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.selected_guilde = None

    @discord.ui.select(
        placeholder="Choisir la guilde à modifier...",
        options=[discord.SelectOption(label=g) for g in ALLIANCE_GUILDES]
    )
    async def select_guilde(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_guilde = select.values[0]
        
        # Barème conforme à ton système
        buttons = [
            ("Prisme Win (+15)", 15, discord.ButtonStyle.success),
            ("Prisme Win (+10)", 10, discord.ButtonStyle.success),
            ("Perco Atk (+3)", 3, discord.ButtonStyle.primary),
            ("Perco Def (+2)", 2, discord.ButtonStyle.primary),
            ("Bonus Mixte/Time (+1)", 1, discord.ButtonStyle.secondary),
            ("Correction (-5)", -5, discord.ButtonStyle.danger),
        ]

        view = discord.ui.View()
        for label, val, style in buttons:
            btn = discord.ui.Button(label=label, style=style)
            
            # Utilisation d'une fonction wrapper pour capturer la valeur 'val'
            def create_callback(v):
                async def callback(inter):
                    data = load_data()
                    if self.selected_guilde not in data["guildes"]:
                        data["guildes"][self.selected_guilde] = 0
                    data["guildes"][self.selected_guilde] += v
                    save_data(data)
                    await inter.response.send_message(f"✅ **{v}** pts pour **{self.selected_guilde}**.", ephemeral=True)
                return callback
            
            btn.callback = create_callback(val)
            view.add_item(btn)

        await interaction.response.edit_message(content=f"⚙️ Modification : **{self.selected_guilde}**", view=view)

class CombatWizard(discord.ui.View):
    def __init__(self, user, bot_instance):
        super().__init__(timeout=300)
        self.user = user
        self.bot = bot_instance
        self.guildes_choisies = []
        self.type_combat = None
        self.format = None
        self.issue = None
        self.mixte = False
        self.long_combat = False

    @discord.ui.select(
        placeholder="Sélectionne la ou les guildes (max 4)...",
        min_values=1, max_values=4,
        options=[discord.SelectOption(label=g) for g in ALLIANCE_GUILDES]
    )
    async def select_guilde(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.guildes_choisies = select.values
        self.mixte = len(self.guildes_choisies) > 1
        
        view = discord.ui.View()
        types = [("Prisme", "Prisme"), ("Perco (Atk)", "Perco_Atk"), ("Perco (Def)", "Perco_Def")]
        
        for label, val in types:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            def make_cb(v):
                async def cb(inter):
                    self.type_combat = v
                    if v == "Perco_Def": 
                        self.format = "4v4"
                        await self.show_issue(inter)
                    else: 
                        await self.show_format(inter)
                return cb
            btn.callback = make_cb(val)
            view.add_item(btn)
        
        await interaction.response.edit_message(content=f"✅ Guildes : **{', '.join(self.guildes_choisies)}**\n**Étape 2 :** Type de combat ?", view=view)

    async def show_format(self, interaction):
        view = discord.ui.View()
        formats = [("4v4 Full", "4v4"), ("4v3/2 Partiel", "4v3/2"), ("4v1/0 No Def", "4v1/0")]
        for label, val in formats:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            def make_cb(v):
                async def cb(inter):
                    self.format = v
                    await self.show_issue(inter)
                return cb
            btn.callback = make_cb(val)
            view.add_item(btn)
        await interaction.response.edit_message(content="**Étape 3 :** Format adverse ?", view=view)

    async def show_issue(self, interaction):
        view = discord.ui.View()
        for res in ["Victoire", "Défaite"]:
            btn = discord.ui.Button(label=res, style=discord.ButtonStyle.success if res=="Victoire" else discord.ButtonStyle.danger)
            def make_cb(r):
                async def cb(inter):
                    self.issue = r
                    await self.show_bonus(inter)
                return cb
            btn.callback = make_cb(res)
            view.add_item(btn)
        await interaction.response.edit_message(content="**Étape 4 :** Résultat ?", view=view)

    async def show_bonus(self, interaction):
        view = discord.ui.View()
        btn_mixte = discord.ui.Button(label="Team Mixte ✅" if self.mixte else "Team Mixte ?", style=discord.ButtonStyle.blurple)
        async def cb_m(inter):
            self.mixte = not self.mixte
            await self.show_bonus(inter)
        btn_mixte.callback = cb_m

        btn_long = discord.ui.Button(label="+30min ✅" if self.long_combat else "+30min ?", style=discord.ButtonStyle.blurple)
        async def cb_l(inter):
            self.long_combat = not self.long_combat
            await self.show_bonus(inter)
        btn_long.callback = cb_l

        btn_fin = discord.ui.Button(label="VALIDER ET ENVOYER SCREEN", style=discord.ButtonStyle.green, row=1)
        btn_fin.callback = self.finish
        
        view.add_item(btn_mixte); view.add_item(btn_long); view.add_item(btn_fin)
        await interaction.response.edit_message(content="**Dernière étape :** Bonus éventuels ?", view=view)

    async def finish(self, interaction: discord.Interaction):
        pts = 0
        win = (self.issue == "Victoire")
        if self.type_combat == "Prisme":
            if win: pts = {"4v4": 15, "4v3/2": 10, "4v1/0": 7}.get(self.format, 7)
            elif self.format == "4v4" and self.long_combat: pts = 1
        elif self.type_combat == "Perco_Atk":
            if win: pts = {"4v4": 3, "4v3/2": 2, "4v1/0": 1}.get(self.format, 1)
        elif self.type_combat == "Perco_Def" and win: pts = 2

        if self.mixte: pts += 1
        if self.long_combat and win: pts += 1

        await interaction.response.edit_message(content=f"🏁 **Résumé : {pts} points.**\nEnvoie ton **SCREENSHOT** maintenant !", view=None)

        try:
            msg = await self.bot.wait_for("message", check=lambda m: m.author == self.user and m.attachments, timeout=300)
            data = load_data()
            uid = str(self.user.id)
            guilde_disp = self.guildes_choisies[0] if len(self.guildes_choisies) == 1 else "MIXTE"
            
            if uid not in data["users"]:
                data["users"][uid] = {"name": self.user.display_name, "guilde": guilde_disp, "pts": 0, "w": 0, "l": 0}
            
            data["users"][uid]["pts"] += pts
            if win: data["users"][uid]["w"] += 1
            else: data["users"][uid]["l"] += 1
            save_data(data)
            await msg.reply(f"✅ Combat validé ! +{pts} pts pour **{self.user.display_name}**.")
        except:
            await interaction.followup.send("⏳ Temps écoulé pour l'envoi du screenshot.", ephemeral=True)

# --- CLASSE DU BOT ---
class RushBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())

    async def setup_hook(self):
        self.update_dashboard.start()
        await self.tree.sync()

    @tasks.loop(minutes=5)
    async def update_dashboard(self):
        channel = self.get_channel(DASHBOARD_CHANNEL_ID)
        if not channel: return
        data = load_data()
        embed = generate_leaderboard_embed(data, "📊 DASHBOARD LIVE - RUSH ALLIANCE")
        async for message in channel.history(limit=5):
            if message.author == self.user and message.embeds:
                await message.edit(embed=embed)
                return
        await channel.send(embed=embed)

# --- INSTANCIATION DU BOT (CRUCIAL ICI) ---
bot = RushBot()

# --- COMMANDES SLASH ---

@bot.tree.command(name="admin_guilde", description="Modifier les points d'une guilde via boutons (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def admin_guilde(interaction: discord.Interaction):
    await interaction.response.send_message("Menu de gestion des guildes :", view=GuildePointsView(), ephemeral=True)

@bot.tree.command(name="ajouter_combat", description="Enregistrer un nouveau combat de rush")
async def add(interaction: discord.Interaction):
    await interaction.response.send_message("Formulaire combat :", view=CombatWizard(interaction.user, bot), ephemeral=True)

@bot.tree.command(name="classement", description="Affiche le classement actuel")
async def classement(interaction: discord.Interaction):
    data = load_data()
    await interaction.response.send_message(embed=generate_leaderboard_embed(data))

@bot.tree.command(name="admin_points", description="Modifier les points d'un joueur")
@app_commands.checks.has_permissions(administrator=True)
async def admin_points(interaction: discord.Interaction, membre: discord.Member, points: int):
    data = load_data()
    uid = str(membre.id)
    if uid not in data["users"]:
        data["users"][uid] = {"name": membre.display_name, "guilde": "INCONNUE", "pts": 0, "w": 0, "l": 0}
    data["users"][uid]["pts"] += points
    save_data(data)
    await interaction.response.send_message(f"✅ Points mis à jour pour {membre.display_name}.", ephemeral=True)

# --- LANCEMENT ---
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("ERREUR : TOKEN manquant.")
