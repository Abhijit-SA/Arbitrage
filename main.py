import asyncio
import csv
import os
import time
import tkinter as tk
import urllib.request
from datetime import datetime
from datetime import timedelta

import aiohttp
import customtkinter
import nest_asyncio  # ? to avoid a possible conflict
import pandas as pd
import requests
from alive_progress import alive_bar
from PIL import Image
from PIL import ImageTk

# * Define the region and trade hub locations as a tuple of dictionaries
regions = (
    {"name": "Jita", "region_id": 10000002, "location_id": 60003760},
    {"name": "Amarr", "region_id": 10000043, "location_id": 60008494},
    {"name": "Rens", "region_id": 10000030, "location_id": 60004588},
    {"name": "Dodixie", "region_id": 10000032, "location_id": 60011866},
    {"name": "Hek", "region_id": 10000042, "location_id": 60005686},
)
tax = [8, 7.12, 6.24, 5.36, 4.48, 3.60]
orderType = ["buy", "sell"]


# ! Retrieve Static Data from www.fuzzwork.co.uk
def get_data():
    base_url = "https://www.fuzzwork.co.uk/dump/latest/"
    local_files = [
        "invTypes-nodescription.csv",
        "invMarketGroups.csv",
    ]

    # Create the 'static' folder is it doesn't exist
    if not os.path.exists("static"):
        os.makedirs("static")

    for file_name in local_files:
        local_file_path = os.path.join(os.path.abspath("static"), file_name)

        def download():
            with alive_bar(title=f"Downloading latest {file_name}") as bar:
                urllib.request.urlretrieve(
                    base_url + file_name,
                    local_file_path,
                    reporthook=lambda count, block_size, total_size: bar(),
                )

        if os.path.isfile(local_file_path):
            local_modified_time = os.path.getmtime(local_file_path)

            remote_modified_time = (
                urllib.request.urlopen(base_url + file_name)
                .info()
                .get("Last-Modified")
            )
            remote_modified_time = time.strptime(
                remote_modified_time, "%a, %d %b %Y %H:%M:%S %Z"
            )

            if time.gmtime(local_modified_time) < remote_modified_time:
                print(f"{file_name} is out of date.")
                download()
            else:
                print(f"{file_name} is up to date")
        else:
            print(f"{file_name} does not exist.")
            download()


# * Static data import
def static_data(market_groups):
    column_names = [
        "type_id",
        "group_id",
        "type_name",
        "mass",
        "volume",
        "capacity",
        "portionSize",
        "raceID",
        "basePrice",
        "published",
        "marketGroupID",
        "iconID",
        "soundID",
        "graphicID",
    ]  # typeID,groupID,typeName,description,mass,volume,capacity,portionSize,raceID,basePrice,published,marketGroupID,iconID,soundID,graphicID
    static_data_file = os.path.join("static", "invTypes-nodescription.csv")
    static_data = pd.read_csv(static_data_file, names=column_names)
    static_data = static_data.drop(
        ["mass", "soundID", "iconID", "graphicID"], axis=1
    )
    max_volume = 1000000
    static_data = static_data[static_data["volume"] <= max_volume]
    static_data = static_data[static_data.marketGroupID != "\\N"]
    static_data = static_data[static_data.published != 0]
    static_data = static_data.drop(["raceID", "published"], axis=1)
    static_data = static_data.sort_values(["type_id"])
    static_data["marketGroupID"] = static_data["marketGroupID"].astype(int)
    static_data["marketGroupID"] = static_data["marketGroupID"].apply(
        lambda x: find_root_group(x, market_groups)
    )
    return static_data


# @param group_names: Accepts list of groupNames
# returns list of groupIDs
def get_group_ids(group_names):
    market_groups_dict = market_groups()
    group_ids = []
    for group_id, group_data in market_groups_dict.items():
        if group_data["name"] in group_names:
            group_ids.append(group_id)
    return group_ids


def market_groups():
    file_path = os.path.join("static", "invMarketGroups.csv")
    with open(file_path) as file:
        csv_reader = csv.reader(file, delimiter=",")
        # skip the header row
        next(csv_reader)
        market_groups = {}
        for row in csv_reader:
            group_id = int(row[0])
            parent_id = int(row[1]) if row[1] != "None" else 0
            group_name = row[2]
            market_groups[group_id] = {
                "name": group_name,
                "parentGroupID": parent_id,
                "subGroups": [],
            }

        for group_id, group_data in market_groups.items():
            parent_id = group_data["parentGroupID"]
            if parent_id in market_groups:
                parent_group_data = market_groups[parent_id]
                parent_group_data["subGroups"].append(group_id)
                group_data["parentGroupID"] = parent_id
            else:
                group_data["parentGroupID"] = None
    return market_groups


def find_root_group(group_id, market_groups):
    root_group_id = group_id
    while market_groups[root_group_id]["parentGroupID"] is not None:
        root_group_id = market_groups[root_group_id]["parentGroupID"]
    return root_group_id


# * Extract region name from regions
def get_region_name(region_id):
    for region in regions:
        if region["region_id"] == region_id:
            return region["name"]
    return None


# * From 'regions' tuple extract 'location_id'
def get_location_id(region_id):
    for region in regions:
        if region["region_id"] == region_id:
            return region["location_id"]
    return None


# * From 'regions' tuple extract 'name'
def get_region_id(name):
    for region in regions:
        if region["name"] == name:
            return region["region_id"]
    return None


# Write the item list to txt file
def write_to_file(items_list, buy_region, sell_region):
    if not os.path.exists("output"):
        os.makedirs("output")
    now = datetime.now()
    file_name = f"{get_region_name(buy_region)}_{get_region_name(sell_region)}_{now.strftime('%H-%M_%d-%m-%y')}.txt"
    file_path = os.path.join("output", file_name)
    with open(file_path, "w") as file:
        file.write(str(items_list))
    # Open the file explorer window and select the output file
    # subprocess.Popen(['xdg-open', os.path.dirname(file_path)])


# check for cache file
def cache_check(buy_region, sell_region):
    if not os.path.exists("cache"):
        os.makedirs("cache")

    # Define the names of the CSV files
    csv_file_name = os.path.join(
        "cache",
        f"{get_region_name(buy_region)}_{get_region_name(sell_region)}.csv",
    )

    # Define the time delta (2 minutes in this case)
    time_delta = timedelta(minutes=2)

    if os.path.exists(csv_file_name):
        # If the CSV file exists, check when it was created
        file_time = datetime.fromtimestamp(os.path.getmtime(csv_file_name))

        if datetime.now() - file_time < time_delta:
            # file was created less than 2 minutes ago
            return 1

        else:
            # file is older than 2 minutes
            return 0
    else:
        # CSV file does not exist
        return 0


# Homogenised market_pull function
nest_asyncio.apply()


async def fetch(session, url):
    async with session.get(url) as response:
        return await response.json()


async def fetch_all(session, urls):
    results = await asyncio.gather(*[fetch(session, url) for url in urls])
    return results


# * Pull market data
async def marketPull(region, orderType):
    url = f"https://esi.evetech.net/latest/markets/{region}/orders/?datasource=tranquility&order_type={orderType}"
    response = requests.get(url)
    if response.status_code != 200:
        exit(
            f"Error fetching orders from {region} ({orderType}): {response.text}"
        )
    total_pages = int(response.headers["X-Pages"])
    urls = [f"{url}&page={page}" for page in range(1, total_pages + 1)]
    print(
        f"Fetching {total_pages} pages from {get_region_name(region)}, please wait..."
    )

    async with aiohttp.ClientSession() as session:
        responses = await fetch_all(session, urls)

    market_pull = pd.concat(
        [pd.DataFrame(r) for r in responses], ignore_index=True
    )
    market_pull = market_pull.sort_values(
        ["type_id", "price"]
    ).drop_duplicates(
        "type_id", keep="first"
    )  # keep only the order with lowest price

    total_data_used = round(
        (sum(len(response) for response in responses)) * 0.001, 2
    )
    print(
        f"{get_region_name(region)} market pull complete. Total data used: {total_data_used} KB."
    )

    return market_pull


# * Merge data from two markets
def merge_data(market_buy, buy_region, market_sell, sell_region, static_data):
    orders = pd.DataFrame(
        columns=[
            "type_id",
            "marketGroupID",
            "name",
            "volume",
            "market_buy_price",
            "market_sell_price",
            "available_quantity",
        ]
    )
    market_buy_location = get_location_id(buy_region)
    market_sell_location = get_location_id(sell_region)
    market_buy = market_buy[
        market_buy.location_id == market_buy_location
    ]  # limit orders only to jita 4.4
    market_sell = market_sell[
        market_sell.location_id == market_sell_location
    ]  # limit orders only to amarr trade hub
    # print("debug: created orders, populating market data")
    orders[["type_id", "marketGroupID", "name", "volume"]] = static_data[
        ["type_id", "marketGroupID", "type_name", "volume"]
    ]  # populate name and volume form static_data

    # * Populate 'orders' with market_buy_price, market_sell_price and quantity
    with alive_bar(len(orders), title="Populate market data") as bar:
        for idx, row in orders.iterrows():
            type_id = row["type_id"]
            market_buy_row = market_buy.loc[market_buy["type_id"] == type_id]
            market_sell_row = market_sell.loc[
                market_sell["type_id"] == type_id
            ]

            if not market_buy_row.empty:
                market_buy_price = market_buy_row.iloc[0]["price"]
                available_quantity = market_buy_row.iloc[0]["volume_remain"]
                orders.at[idx, "market_buy_price"] = market_buy_price
                orders.at[idx, "available_quantity"] = available_quantity

            if not market_sell_row.empty:
                market_sell_price = market_sell_row.iloc[0]["price"]
                orders.at[idx, "market_sell_price"] = market_sell_price

            bar()
    file_path = os.path.join(
        "cache",
        f"{get_region_name(buy_region)}_{get_region_name(sell_region)}.csv",
    )
    orders.to_csv(file_path, index=False)
    return orders


# Data cleaning for the orders dataframe
def clean(orders, budget, max_value, taxes, select_groups):
    print("debug: Orders populated, cleaning data")
    # keep orders common in both market
    orders = orders.dropna(subset=["market_buy_price", "market_sell_price"])
    # remove orders above budget
    orders = orders[
        (orders["market_sell_price"] <= budget)
        & (orders["market_buy_price"] <= budget)
    ]

    # calculate profit
    orders["profit"] = (
        orders["market_sell_price"] * (1 - (taxes / 100))
        - orders["market_buy_price"]
    )
    # remove unprofitable orders
    orders = orders[orders["profit"] > 0]
    # sort by highest profit
    orders = orders.sort_values(by="profit", ascending=False)
    # filter items that have value greater than item_max_value
    orders = orders[orders["market_buy_price"] <= max_value]
    # filter market tampered commodities
    orders = orders[
        orders["market_sell_price"] <= 3.5 * orders["market_buy_price"]
    ]
    # filter items that are not in selected market groups
    orders = orders[orders["marketGroupID"].isin(select_groups)]
    print("debug: cleaning complete")
    return orders


# * algorithm
# @param orders : orders df from merge_data
# @param budget : total ISK capital
# @param cargo : total cargo volume
def maximize_profit(orders, budget, cargo):
    print("debug: starting main algorithm")
    # Sort orders by profit per volume in descending order
    orders = orders.sort_values("profit", ascending=False)
    orders["profit_per_volume"] = orders["profit"] / orders["volume"]

    # Initialize variables
    items = []
    total_cost = 0
    total_volume = 0
    total_profit = 0

    # Greedily add items to the order until budget or cargo constraints are reached
    # FIXME: The algorithm can be improved.
    with alive_bar(len(orders), title="Processing Orders") as bar:
        for _, row in orders.iterrows():
            if (
                row["volume"] <= cargo
                and row["market_buy_price"] <= budget
                and row["available_quantity"] > 0
            ):
                # Calculate the maximum quantity that can be purchased within the budget and available quantity
                quantity = int(
                    min(
                        int(budget / row["market_buy_price"]),
                        int(cargo / row["volume"]),
                        row["available_quantity"],
                    )
                )
                # Add the item to the order
                items.append({"name": row["name"], "quantity": quantity})
                # Update total cost, profit, and volume
                total_cost += row["market_buy_price"] * quantity
                total_profit += row["profit"] * quantity
                total_volume += row["volume"] * quantity
                # Update budget and cargo constraints
                budget -= row["market_buy_price"] * quantity
                cargo -= row["volume"] * quantity
            bar()  # increment progress bar
    # remove first line "name", "quantity"
    return items


# * Main function
def arbitrage(
    buy_region,
    sell_region,
    buy_orderType,
    sell_orderType,
    budget,
    cargo,
    taxes,
    max_value,
    select_groups,
):
    market__groups = market_groups()
    static__data = static_data(dict(market__groups))

    # print(f"debug: Starting {get_region_name(buy_region)} market pull...")
    market_buy = asyncio.run(marketPull(buy_region, buy_orderType))
    # print(f"debug: Starting {get_region_name(sell_region)} market pull...")
    market_sell = asyncio.run(marketPull(sell_region, sell_orderType))
    # print("debug: merging market data")
    orders = pd.DataFrame(
        merge_data(
            market_buy, buy_region, market_sell, sell_region, static__data
        )
    )
    return maximize_profit(
        clean(orders, budget, max_value, taxes, select_groups), budget, cargo
    )


def create_frontend(regions, tax):
    market_groups_dict = market_groups()
    static_data(market_groups_dict)
    parent_groups = [
        group_data["name"]
        for group_id, group_data in market_groups_dict.items()
        if group_data["parentGroupID"] is None
    ]

    def run_program():
        class regionError(Exception):
            def __init__(
                self, message="Buy region and Sell region cannot be the same!"
            ):
                self.message = message
                super().__init__(self.message)

        try:
            buy_region_name = buy_region_var.get()
            sell_region_name = sell_region_var.get()

            # exception if buy_region is same as sell_region
            if buy_region_name == sell_region_name:
                raise regionError()

            taxes = int(tax_var.get())
            cargo = cargo_var.get()
            budget = int(budget_var.get())
            max_value = budget * (int(max_value_var.get()) / 100)
            buy_region = get_region_id(buy_region_name)
            sell_region = get_region_id(sell_region_name)
            buy_orderType = buy_orderType_var.get()
            sell_orderType = sell_orderType_var.get()
            # select_groups = [11, 157, 24, 475, 1320, 9, 955, 477, 19]
            select_groups = []
            for i, var in enumerate(checkbox_vars):
                if var.get() == 1:
                    select_groups.append(parent_groups[i])
            select_groups = get_group_ids(select_groups)

            if sell_orderType == "sell" and buy_orderType == "sell":
                taxes = taxes + 1.8
            if sell_orderType == "sell" and buy_orderType == "buy":
                taxes = taxes + 1.8 + 1.8
            if sell_orderType == "buy" and buy_orderType == "buy":
                taxes = taxes + 1.8

            # Main
            if os.name == "posix":
                os.system("clear")
            else:
                os.system("cls")

            def result(item_list):
                window = tk.Toplevel(root)
                window.title("Results")
                window.geometry("800x600")
                window.configure(bg="black")

                def copy_to_clipboard():
                    text = list_text.get(
                        "1.0", "end-1c"
                    )  # get all text from the text widget
                    root.clipboard_clear()  # clear the clipboard
                    root.clipboard_append(
                        text
                    )  # append the text to the clipboard

                list_text = tk.Text(
                    window,
                    bg="black",
                    fg="white",
                    font=("Consolas", 18),
                    wrap=tk.WORD,
                )
                list_text_scrollbar = tk.Scrollbar(
                    window, orient=tk.VERTICAL, command=list_text.yview
                )
                list_text.configure(yscrollcommand=list_text_scrollbar.set)

                tk.Label(
                    window,
                    bg="black",
                    fg="white",
                    text="EVE Arbitrage Results",
                    font=("Consolas", 28),
                ).pack()
                tk.Label(window, bg="black", text="  ").pack()
                copy_button = customtkinter.CTkButton(
                    window,
                    font=("Arial", 25),
                    text="Copy to Clipboard",
                    width=300,
                    command=copy_to_clipboard,
                    border_width=2,
                    fg_color=("lightgray", "black"),
                )
                copy_button.pack()
                tk.Label(window, bg="black", text="  ").pack()
                list_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                list_text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                list_text.insert(tk.END, items_list, buy_region)
                write_to_file(items_list, buy_region, sell_region)

            # ! if a cached orders file exists and is <5 minutes old, use it
            if cache_check(buy_region, sell_region) == 1:
                print("Cache found!")
                orders = pd.read_csv(
                    os.path.join(
                        "cache",
                        f"{get_region_name(buy_region)}_{get_region_name(sell_region)}.csv",
                    )
                )
                orders = clean(orders, budget, max_value, taxes, select_groups)
                items = pd.DataFrame(maximize_profit(orders, budget, cargo))
                items_list = items.to_string(index=False, header=False)
                print(items_list)  # output
                result(items_list)

            else:
                items = pd.DataFrame(
                    arbitrage(
                        buy_region,
                        sell_region,
                        buy_orderType,
                        sell_orderType,
                        budget,
                        cargo,
                        taxes,
                        max_value,
                        select_groups,
                    )
                )
                items_list = items.to_string(index=False, header=False)

                if os.name == "posix":
                    os.system("clear")
                else:
                    os.system("cls")
                print(items_list)
                result(items_list)

        except regionError as e:
            print(e)
            root.mainloop()

    # ! GUI
    # Initialize the tkinter window
    root = tk.Tk()
    root.title("EVE Arbitrage Helper")
    root.geometry("800x700")
    root.configure(bg="black")

    # Create the frames
    regi_frame = tk.Frame(root, bg="black", width=50, height=50)
    regi_frame.grid(row=0, column=0, columnspan=2, pady=10)
    logo = Image.open("res/logo.jpg")

    # Resize the image to fit inside the frame
    new_size = (250, 100)
    logo = logo.resize(new_size)

    # Create a Tkinter-compatible image object
    tk_image = ImageTk.PhotoImage(logo)

    # Create a label to display the image
    image_label = tk.Label(regi_frame, image=tk_image)
    image_label.pack()

    region_frame = tk.Frame(root, bg="black")
    region_frame.grid(row=1, column=0, columnspan=2, pady=10)

    cargo_frame = tk.Frame(root, bg="black")
    cargo_frame.grid(row=2, column=0, columnspan=2, pady=10)

    tax_frame = tk.Frame(root, bg="black")
    tax_frame.grid(row=3, column=0, columnspan=2, pady=10)

    parent_groups_frame = tk.Frame(root, bg="black")
    parent_groups_frame.grid(row=4, column=0, columnspan=2, pady=10)

    run_frame = tk.Frame(root, bg="black")
    run_frame.grid(row=5, column=0, columnspan=2, pady=10)

    # Create the dropdown menus for regions
    buy_region_label = tk.Label(
        region_frame,
        text="Select Trade Hubs and Order Types",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    buy_region_label.pack()

    buy_region_var = tk.StringVar(region_frame)
    buy_region_label = tk.Label(
        region_frame,
        text="Buy Region:",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    buy_region_label.pack(side="left", padx=2)

    buy_region_var.set(regions[0]["name"])  # set the default option
    buy_region_dropdown = tk.OptionMenu(
        region_frame, buy_region_var, *[region["name"] for region in regions]
    )
    buy_region_dropdown.pack(side="left", padx=2)
    buy_region_dropdown.configure(
        bg="black", fg="white", font=("Consolas", 12)
    )
    buy_orderType_var = tk.StringVar(region_frame)
    buy_orderType_var.set(orderType[1])
    buy_orderType_dropdown = tk.OptionMenu(
        region_frame, buy_orderType_var, *orderType
    )
    buy_orderType_dropdown.pack(side="left", padx=2)
    buy_orderType_dropdown.configure(
        bg="black", fg="white", font=("Consolas", 12)
    )

    sell_region_var = tk.StringVar(region_frame)
    sell_region_label = tk.Label(
        region_frame,
        text="Sell Region:",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    sell_region_label.pack(side="left", padx=10)

    sell_region_var.set(regions[1]["name"])  # set the default option
    sell_region_dropdown = tk.OptionMenu(
        region_frame, sell_region_var, *[region["name"] for region in regions]
    )
    sell_region_dropdown.pack(side="left", padx=2)
    sell_region_dropdown.configure(
        bg="black", fg="white", font=("Consolas", 12)
    )

    sell_orderType_var = tk.StringVar(region_frame)
    sell_orderType_var.set(orderType[0])
    sell_orderType_dropdown = tk.OptionMenu(
        region_frame, sell_orderType_var, *orderType
    )
    sell_orderType_dropdown.pack(side="left", padx=2)
    sell_orderType_dropdown.configure(
        bg="black", fg="white", font=("Consolas", 12)
    )

    # Create the widgets for cargo and budget
    cargo_label = tk.Label(
        cargo_frame,
        text="Cargo and Budget",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    cargo_label.pack()

    cargo_label = tk.Label(
        cargo_frame,
        text="Cargo:",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    cargo_label.pack(side="left", padx=2)
    cargo_var = tk.IntVar(cargo_frame)
    cargo_var.set(5000)
    cargo_input = tk.Entry(cargo_frame, textvariable=cargo_var)
    cargo_input.pack(side="left", padx=2)
    cargo_input.configure(
        bg="black", fg="white", font=("Consolas", 12), insertbackground="white"
    )

    budget_label = tk.Label(
        cargo_frame,
        text="Budget:",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    budget_label.pack(side="left", padx=10)
    budget_var = tk.IntVar(cargo_frame)
    budget_var.set(100000000)
    budget_entry = tk.Entry(cargo_frame, textvariable=budget_var)
    budget_entry.pack(side="left", padx=2)
    budget_entry.configure(
        bg="black", fg="white", font=("Consolas", 12), insertbackground="white"
    )

    tax_label = tk.Label(
        tax_frame,
        text="Broker's Fee and Sales Tax (%):",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    tax_label.grid(row=0, column=0, padx=10, pady=2)
    tax_var = tk.IntVar(tax_frame)  # ! has to be int
    tax_var.set(tax[0])
    tax_dropdown = tk.OptionMenu(tax_frame, tax_var, *tax)
    tax_dropdown.grid(row=1, column=0, padx=2, pady=2)
    tax_dropdown.configure(bg="black", fg="white", font=("Consolas", 12))

    max_label = tk.Label(
        tax_frame,
        text="Maximum value per item %",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    max_label.grid(row=0, column=1, padx=10, pady=2)
    max_value_var = tk.IntVar(tax_frame)  # ! has to be int
    max_value_var.set(10)
    # max_value_slider = tk.Scale(tax_frame, from_=1, to=100, orient="horizontal")
    # max_value_slider.grid(row=1, column=1, padx=2, pady=2)
    max_input = tk.Entry(tax_frame, textvariable=max_value_var)
    max_input.grid(row=1, column=1, padx=2, pady=2)
    max_input.configure(
        bg="black", fg="white", font=("Consolas", 12), insertbackground="white"
    )

    # Create a label for the checkbox list
    checkbox_label = tk.Label(
        parent_groups_frame,
        text="Market Groups",
        anchor="center",
        bg="black",
        fg="white",
        font=("Consolas", 12),
    )
    checkbox_label.grid(row=0, column=0, columnspan=3)

    # Loop through the items and create a checkbox for each one
    row = 1
    col = 0
    checked_boxes = []
    checkbox_vars = []  # create a list to hold the checkbox variables
    for i, group in enumerate(parent_groups):
        var = tk.IntVar(
            value=1
        )  # Set the default value to 1 to tick the checkbox
        checkbox = tk.Checkbutton(
            parent_groups_frame,
            font=("Consolas", 12),
            text=group,
            bg="black",
            fg="white",
            selectcolor="black",
            background="black",
            variable=var,
        )
        checkbox.grid(row=row, column=col, sticky="w")
        checkbox_vars.append(var)  # add the variable to the list
        checked_boxes.append(parent_groups[i])
        col += 1
        if col > 2:
            col = 0
            row += 1

    run_button = customtkinter.CTkButton(
        run_frame,
        font=("Arial", 25),
        text="Run",
        width=300,
        command=run_program,
        border_width=2,
        fg_color=("lightgray", "black"),
    )
    run_button.pack(side="left", pady=2)

    # Run the main loop
    root.mainloop()


if __name__ == "__main__":
    get_data()
    create_frontend(regions, tax)

# TODO: Restructure the entire code. Organize into separate classes.
# TODO: Add a profit report!
