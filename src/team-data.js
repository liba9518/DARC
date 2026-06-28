export const TEAM_DATA = [
  ["阿根廷", "Argentina", 1],
  ["法国", "France", 2],
  ["西班牙", "Spain", 3],
  ["英格兰", "England", 4],
  ["巴西", "Brazil", 5],
  ["葡萄牙", "Portugal", 6],
  ["荷兰", "Netherlands", 7],
  ["比利时", "Belgium", 8],
  ["德国", "Germany", 9],
  ["克罗地亚", "Croatia", 10],
  ["乌拉圭", "Uruguay", 11],
  ["摩洛哥", "Morocco", 12],
  ["哥伦比亚", "Colombia", 13],
  ["美国", "USA", 14],
  ["墨西哥", "Mexico", 15],
  ["瑞士", "Switzerland", 16],
  ["日本", "Japan", 17],
  ["塞内加尔", "Senegal", 18],
  ["瑞典", "Sweden", 19],
  ["伊朗", "Iran", 20],
  ["厄瓜多尔", "Ecuador", 21],
  ["韩国", "South Korea", 22],
  ["澳大利亚", "Australia", 23],
  ["挪威", "Norway", 24],
  ["埃及", "Egypt", 25],
  ["加纳", "Ghana", 26],
  ["加拿大", "Canada", 27],
  ["卡塔尔", "Qatar", 28],
  ["沙特阿拉伯", "Saudi Arabia", 29],
  ["南非", "South Africa", 30],
  ["土耳其", "Turkiye", 31],
  ["奥地利", "Austria", 32],
  ["捷克", "Czech Republic", 33],
  ["科特迪瓦", "Ivory Coast", 34],
  ["突尼斯", "Tunisia", 35],
  ["阿尔及利亚", "Algeria", 36],
  ["巴拉圭", "Paraguay", 37],
  ["苏格兰", "Scotland", 38],
  ["乌兹别克斯坦", "Uzbekistan", 39],
  ["巴拿马", "Panama", 40],
  ["新西兰", "New Zealand", 41],
  ["伊拉克", "Iraq", 42],
  ["约旦", "Jordan", 43],
  ["佛得角", "Cape Verde", 44],
  ["波黑", "Bosnia-Herzegovina", 45],
  ["刚果（金）", "DR Congo", 46],
  ["海地", "Haiti", 47],
  ["库拉索", "Curacao", 48]
].map(([zh, en, rank]) => ({ zh, en, rank }));

const ALIASES = {
  "美國": "USA",
  "United States": "USA",
  "South Korea": "South Korea",
  "韓國": "South Korea",
  "Türkiye": "Turkiye",
  "Turkey": "Turkiye",
  "Bosnia & Herzegovina": "Bosnia-Herzegovina",
  "Bosnia and Herzegovina": "Bosnia-Herzegovina",
  "Curaçao": "Curacao",
  "Côte d'Ivoire": "Ivory Coast",
  "Congo DR": "DR Congo",
  "IR Iran": "Iran",
  "Islamic Republic of Iran": "Iran",
  "Cabo Verde": "Cape Verde"
};

const TEAM_BY_NAME = new Map();
for (const team of TEAM_DATA) {
  TEAM_BY_NAME.set(normalizeName(team.zh), team);
  TEAM_BY_NAME.set(normalizeName(team.en), team);
}
for (const [alias, canonical] of Object.entries(ALIASES)) {
  const team = TEAM_BY_NAME.get(normalizeName(canonical));
  if (team) {
    TEAM_BY_NAME.set(normalizeName(alias), team);
  }
}

export function resolveTeam(name) {
  return TEAM_BY_NAME.get(normalizeName(name)) ?? {
    zh: name,
    en: name,
    rank: 48
  };
}

export function normalizeTeamName(name) {
  return resolveTeam(name).en;
}

export function normalizeName(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9\u4e00-\u9fff]+/g, " ")
    .trim()
    .toLowerCase();
}
