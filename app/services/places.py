"""South African cities and towns with their provinces, suggested as the applicant types their location
(1 Nov 2026, at the user's request). Kept in the system on purpose: no maps service, nothing typed leaves the site.
Renamed places list the new name with the old one in brackets, so either can be typed."""

PROVINCE_PLACES = {
    "Eastern Cape": [
        "Aliwal North", "Bhisho", "Butterworth", "Cradock", "East London", "Fort Beaufort", "Gqeberha (Port Elizabeth)",
        "Graaff-Reinet", "Humansdorp", "Idutywa", "Jeffreys Bay", "Kariega (Uitenhage)", "Komani (Queenstown)",
        "Lusikisiki", "Makhanda (Grahamstown)", "Matatiele", "Mdantsane", "Mount Ayliff", "Mount Frere", "Mthatha",
        "Port Alfred", "Port St Johns", "Qonce (King William's Town)", "Somerset East",
    ],
    "Free State": [
        "Bethlehem", "Bloemfontein", "Bothaville", "Botshabelo", "Ficksburg", "Frankfort", "Harrismith", "Heilbron",
        "Hennenman", "Jagersfontein", "Koffiefontein", "Kroonstad", "Ladybrand", "Odendaalsrus", "Parys",
        "Phuthaditjhaba", "Sasolburg", "Senekal", "Smithfield", "Thaba Nchu", "Theunissen", "Virginia", "Welkom",
        "Zastron",
    ],
    "Gauteng": [
        "Alberton", "Atteridgeville", "Benoni", "Boksburg", "Brakpan", "Bronkhorstspruit", "Carletonville",
        "Centurion", "Cullinan", "Diepsloot", "Edenvale", "Fourways", "Germiston", "Heidelberg", "Johannesburg",
        "Kempton Park", "Krugersdorp", "Mamelodi", "Meyerton", "Midrand", "Nigel", "Pretoria", "Randburg",
        "Randfontein", "Roodepoort", "Sandton", "Soshanguve", "Soweto", "Springs", "Tembisa", "Vanderbijlpark",
        "Vereeniging", "Westonaria",
    ],
    "KwaZulu-Natal": [
        "Amanzimtoti", "Ballito", "Chatsworth", "Dundee", "Durban", "Empangeni", "Eshowe", "Estcourt", "Glencoe",
        "Greytown", "Hluhluwe", "Howick", "Ixopo", "Kokstad", "KwaDukuza (Stanger)", "KwaMashu", "Ladysmith",
        "Margate", "Mooi River", "Mtubatuba", "Newcastle", "Phoenix", "Pietermaritzburg", "Pinetown",
        "Port Shepstone", "Richards Bay", "Scottburgh", "Tongaat", "Ulundi", "Umhlanga", "Umlazi", "Verulam",
        "Vryheid",
    ],
    "Limpopo": [
        "Bela-Bela", "Burgersfort", "Giyani", "Groblersdal", "Hoedspruit", "Jane Furse", "Lebowakgomo", "Lephalale",
        "Makhado (Louis Trichardt)", "Mankweng", "Marble Hall", "Modimolle", "Mokopane", "Musina", "Phalaborwa",
        "Polokwane", "Seshego", "Thabazimbi", "Thohoyandou", "Tzaneen",
    ],
    "Mpumalanga": [
        "Barberton", "Bethal", "Bushbuckridge", "Carolina", "Delmas", "eMakhazeni (Belfast)", "eMalahleni (Witbank)",
        "eMkhondo (Piet Retief)", "Ermelo", "Graskop", "Hazyview", "Kabokweni", "Komatipoort", "Kriel", "KwaMhlanga",
        "Malelane", "Mashishing (Lydenburg)", "Mbombela (Nelspruit)", "Middelburg", "Sabie", "Secunda", "Siyabuswa",
        "Standerton", "Volksrust", "White River",
    ],
    "North West": [
        "Brits", "Christiana", "Coligny", "Hartbeespoort", "Jouberton", "Klerksdorp", "Koster", "Lichtenburg",
        "Mahikeng (Mafikeng)", "Mogwase", "Orkney", "Phokeng", "Potchefstroom", "Rustenburg", "Schweizer-Reneke",
        "Stilfontein", "Swartruggens", "Taung", "Vryburg", "Wolmaransstad", "Zeerust",
    ],
    "Northern Cape": [
        "Barkly West", "Calvinia", "Carnarvon", "Colesberg", "De Aar", "Douglas", "Hartswater", "Jan Kempdorp",
        "Kakamas", "Kathu", "Keimoes", "Kimberley", "Kuruman", "Port Nolloth", "Postmasburg", "Prieska", "Springbok",
        "Sutherland", "Upington", "Victoria West", "Warrenton",
    ],
    "Western Cape": [
        "Atlantis", "Beaufort West", "Bellville", "Caledon", "Cape Town", "Ceres", "Durbanville", "George",
        "Gordon's Bay", "Grabouw", "Hermanus", "Khayelitsha", "Knysna", "Kuils River", "Malmesbury", "Mitchells Plain",
        "Mossel Bay", "Oudtshoorn", "Paarl", "Plettenberg Bay", "Robertson", "Saldanha", "Somerset West",
        "Stellenbosch", "Strand", "Swellendam", "Vredenburg", "Wellington", "Worcester",
    ],
}

# "City, Province", sorted by place name: the suggestions shown in the Location box.
SA_PLACES = sorted((f"{place}, {province}" for province, places in PROVINCE_PLACES.items() for place in places),
                   key=str.lower)
