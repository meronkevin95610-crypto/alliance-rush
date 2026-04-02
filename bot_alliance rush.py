import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os

# --- CONFIGURATION ---
TOKEN = "MTQ4OTM1MTgyNDY1Mjg5NDQwOA.GVYlok.JthQk6x7QKvyh37UwwlfLfIZ2nPaA2O-LdJJNw"
DATA_FILE = "stats_rush_event.json"
DASHBOARD_CHANNEL_ID = 1473418141160837140 # Ton salon de classement

ALLIANCE_GUILDES = [
    "OLYMPE", "EXODE", "LACOSTE TN", "THE UNKNOWNS", "GUCCI MOB",
    "OLD SCHOOL", "NONOOB", "STELLAR", "OLY2", "TU2", "STL2"
]

# --- GESTION DES DONNÉES ---
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding='utf-8') as f:
            return json.load(f)
    return {"users": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- INTERFACE WIZARD ---
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
        placeholder="Sélectionne la ou les guildes présentes (max 4)...",
        min_values=1, max_values=4,
        options=[discord.SelectOption(label=g) for g in ALLIANCE_GUILDES]
    )
    async def select_guilde(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.guildes_choisies = select.values
        if len(self.guildes_choisies) > 1:
            self.mixte = True
            
        view = discord.ui.View()
        types = [("Prisme", "Prisme"), ("Perco (Atk)", "Perco_Atk"), ("Perco (Def)", "Perco_Def")]
        for label, val in types:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            async def cb(inter, v=val):
                self.type_combat = v
                if v == "Perco_Def": 
                    self.format = "4v4"
                    await self.show_issue(inter)
                else: 
                    await self.show_format(inter)
            btn.callback = cb
            view.add_item(btn)
        
        await interaction.response.edit_message(
            content=f"✅ Guildes : **{', '.join(self.guildes_choisies)}**\n**Étape 2 :** Type de combat ?", view=view
        )

    async def show_format(self, interaction):
        view = discord.ui.View()
        formats = [("4v4 Full", "4v4"), ("4v3/2 Partiel", "4v3/2"), ("4v1/0 No Def", "4v1/0")]
        for label, val in formats:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            async def cb(inter, v=val):
                self.format = v
                await self.show_issue(inter)
            btn.callback = cb
            view.add_item(btn)
        await interaction.response.edit_message(content="**Étape 3 :** Quel était le format adverse ?", view=view)

    async def show_issue(self, interaction):
        view = discord.ui.View()
        for res in ["Victoire", "Défaite"]:
            btn = discord.ui.Button(label=res, style=discord.ButtonStyle.success if res=="Victoire" else discord.ButtonStyle.danger)
            async def cb(inter, r=res):
                self.issue = r
                await self.show_bonus(inter)
            btn.callback = cb
            view.add_item(btn)
        await interaction.response.edit_message(content="**Étape 4 :** Résultat du combat ?", view=view)

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

        await interaction.response.edit_message(content=f"🏁 **Résumé : {pts} points.**\nPoste ton **SCREENSHOT** maintenant !", view=None)

        try:
            msg = await self.bot.wait_for("message", check=lambda m: m.author == self.user and m.attachments, timeout=300)
            data = load_data()
            uid = str(self.user.id)
            guilde_disp = self.guildes_choisies[0] if len(self.guildes_choisies) == 1 else "MIXTE"
            
            if uid not in data["users"]:
                data["users"][uid] = {"name": self.user.display_name, "guilde": guilde_disp, "pts": 0, "w": 0, "l": 0}
            else:
                data["users"][uid]["guilde"] = guilde_disp
            
            data["users"][uid]["pts"] += pts
            if win: data["users"][uid]["w"] += 1
            else: data["users"][uid]["l"] += 1
            save_data(data)
            await msg.reply(f"✅ Combat validé ! +{pts} pts.")
        except:
            await interaction.followup.send("⏳ Temps écoulé pour le screen.", ephemeral=True)

# --- BOT SETUP ---
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
        if not data["users"]: return

        sorted_u = sorted(data["users"].items(), key=lambda x: x[1]["pts"], reverse=True)
        embed = discord.Embed(title="📊 CLASSEMENT RUSH ALLIANCE", color=0x2ecc71)
        table = "```\nPos | Joueur (Guilde) | Pts | W/L\n" + "-"*32 + "\n"
        for i, (uid, s) in enumerate(sorted_u[:25], 1):
            table += f"{i:<3} | {s['name'][:10]} ({s['guilde'][:5]}) | {s['pts']:<3} | {s['w']}/{s['l']}\n"
        table += "```"
        embed.description = table
        embed.set_footer(text="Mise à jour auto toutes les 5 min")

        async for message in channel.history(limit=5):
            if message.author == self.user and message.embeds:
                await message.edit(embed=embed)
                return
        await channel.send(embed=embed)

bot = RushBot()

@bot.tree.command(name="ajouter_combat")
async def add(interaction: discord.Interaction):
    await interaction.response.send_message("Initialisation...", view=CombatWizard(interaction.user, bot), ephemeral=True)

@bot.tree.command(name="modifier_points")
async def modif(interaction: discord.Interaction, membre: discord.Member, points: int):
    if not interaction.user.guild_permissions.administrator: return
    data = load_data()
    uid = str(membre.id)
    if uid in data["users"]:
        data["users"][uid]["pts"] += points
        save_data(data)
        await interaction.response.send_message(f"Points mis à jour pour {membre.name}.")

bot.run(TOKEN)