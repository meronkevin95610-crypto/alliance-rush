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
    
    # Section Joueurs
    if data["users"]:
        sorted_u = sorted(data["users"].items(), key=lambda x: x[1]["pts"], reverse=True)
        table_u = "```\nPos | Joueur (Guilde) | Pts\n" + "-"*28 + "\n"
        for i, (uid, s) in enumerate(sorted_u[:15], 1):
            table_u += f"{i:<3} | {s['name'][:10]:<10} ({s['guilde'][:5]:<5}) | {s['pts']}\n"
        table_u += "```"
        embed.add_field(name="🏆 Top Joueurs", value=table_u, inline=False)

    # Section Guildes
    if data.get("guildes"):
        sorted_g = sorted(data["guildes"].items(), key=lambda x: x[1], reverse=True)
        table_g = "```\nPos | Nom de Guilde   | Pts\n" + "-"*28 + "\n"
        for i, (name, pts) in enumerate(sorted_g, 1):
            table_g += f"{i:<3} | {name:<15} | {pts}\n"
        table_g += "```"
        embed.add_field(name="🏰 Classement Guildes", value=table_g, inline=False)
    
    return embed

# --- INTERFACE ADMIN GUILDE (BOUTONS) ---
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
        
        # Barème basé sur votre logique actuelle
        buttons = [
            ("Prisme Win (+15)", 15, discord.ButtonStyle.success),
            ("Prisme Win (+10)", 10, discord.ButtonStyle.success),
            ("Perco Atk (+3)", 3, discord.ButtonStyle.primary),
            ("Perco Def (+2)", 2, discord.ButtonStyle.primary),
            ("Bonus Mixte/Time (+1)", 1, discord.ButtonStyle.secondary),
            ("Retirer (-5)", -5, discord.ButtonStyle.danger),
        ]

        view = discord.ui.View()
        for label, val, style in buttons:
            btn = discord.ui.Button(label=label, style=style)
            async def make_cb(v):
                async def callback(inter):
                    data = load_data()
                    if self.selected_guilde not in data["guildes"]:
                        data["guildes"][self.selected_guilde] = 0
                    
                    data["guildes"][self.selected_guilde] += v
                    save_data(data)
                    await inter.response.send_message(f"✅ **{v}** points appliqués à **{self.selected_guilde}**.", ephemeral=True)
                return callback
            btn.callback = await make_cb(val)
            view.add_item(btn)

        await interaction.response.edit_message(content=f"⚙️ Modification : **{self.selected_guilde}**\nCliquez sur une option du barème :", view=view)

# --- (Gardez vos classes CombatWizard et RushBot identiques à votre code précédent ici) ---
# [ ... Code CombatWizard ... ]
# [ ... Code RushBot ... ]

# --- NOUVELLE COMMANDE ADMIN GUILDE ---
@bot.tree.command(name="admin_guilde", description="Modifier les points d'une guilde via boutons (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def admin_guilde(interaction: discord.Interaction):
    await interaction.response.send_message("Sélectionnez une guilde pour modifier ses points :", view=GuildePointsView(), ephemeral=True)

# --- (Gardez vos autres commandes existantes : ajouter_combat, classement, admin_points) ---

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("ERREUR : TOKEN manquant.")
