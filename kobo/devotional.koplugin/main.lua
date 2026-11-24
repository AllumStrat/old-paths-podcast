--[[--
Devotional: a full-screen list of the daily Old Paths devo EPUBs.

* Lists EPUBs in DEVO_DIR (newest first), with date, plan day and read status.
* "Sync now" runs KOReader's own cloud storage sync for the server named
  SERVER_NAME (settings/cloudstorage.lua), so no Dropbox code lives here.
* Tap opens the book; long-press offers mark read/unread and delete.
* Dispatcher action `devotional_show` (event ShowDevotional) for gestures
  and Zen UI custom navbar tabs.
--]]--

local BookList = require("ui/widget/booklist")
local ButtonDialog = require("ui/widget/buttondialog")
local ConfirmBox = require("ui/widget/confirmbox")
local DocSettings = require("docsettings")
local Device = require("device")
local Dispatcher = require("dispatcher")
local InfoMessage = require("ui/widget/infomessage")
local Menu = require("ui/widget/menu")
local NetworkMgr = require("ui/network/manager")
local Notification = require("ui/widget/notification")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local _ = require("gettext")
local T = require("ffi/util").template

local Screen = Device.screen

local DEVO_DIR = "/mnt/onboard/Devo"
local SERVER_NAME = "Old Paths Devo"

local MONTHS = { "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" }
local DAYS = { "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat" }

-- Parses "YYYY-MM-DD-old-paths-devo-<planday>.epub". Tolerates any other .epub name.
local function parseName(filename)
    local base = filename:gsub("%.[Ee][Pp][Uu][Bb]$", "")
    local y, m, d = base:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)")
    local planday = base:match("devo%-(.+)$")
    local date_str
    if y then
        local ts = os.time{ year = tonumber(y), month = tonumber(m), day = tonumber(d), hour = 12 }
        local wd = os.date("*t", ts).wday
        date_str = string.format("%s %s %d", DAYS[wd], MONTHS[tonumber(m)] or "?", tonumber(d))
    end
    return date_str, planday, base
end

local Devotional = WidgetContainer:extend{
    name = "devotional",
    is_doc_only = false,
}

function Devotional:onDispatcherRegisterActions()
    Dispatcher:registerAction("devotional_show", {
        category = "none",
        event = "ShowDevotional",
        title = _("Devotional"),
        general = true,
        filemanager = true,
    })
end

function Devotional:init()
    self:onDispatcherRegisterActions()
    if self.ui and self.ui.menu then
        self.ui.menu:registerToMainMenu(self)
    end
end

function Devotional:addToMainMenu(menu_items)
    menu_items.devotional = {
        text = _("Devotional"),
        sorting_hint = "tools",
        callback = function() self:show() end,
    }
end

function Devotional:onShowDevotional()
    self:show()
    return true
end

-- Returns array of { file, date, planday, base, status, pct } newest first.
function Devotional:scan()
    local entries = {}
    if lfs.attributes(DEVO_DIR, "mode") ~= "directory" then
        return entries, false
    end
    local ok, iter, dir_obj = pcall(lfs.dir, DEVO_DIR)
    if not ok then return entries, false end
    for f in iter, dir_obj do
        if f:lower():match("%.epub$") and not f:match("^%.") then
            local path = DEVO_DIR .. "/" .. f
            if lfs.attributes(path, "mode") == "file" then
                local date_str, planday, base = parseName(f)
                table.insert(entries, { file = path, name = f, date = date_str, planday = planday, base = base })
            end
        end
    end
    table.sort(entries, function(a, b) return a.name > b.name end)
    for _i, e in ipairs(entries) do
        self:readStatus(e)
    end
    return entries, true
end

-- status: "unread" | "reading" | "read"
function Devotional:readStatus(e)
    BookList.resetBookInfoCache(e.file) -- the reader may have changed the sidecar
    local info = BookList.getBookInfo(e.file) -- no sidecar -> been_opened=false
    local pct = info.percent_finished
    if not info.been_opened then
        e.status = "unread"
    elseif info.status == "complete" then
        e.status = "read"
    elseif pct and pct > 0 then
        e.status = "reading"
        e.pct = math.floor(pct * 100 + 0.5)
    else
        e.status = "unread"
    end
end

local function statusText(e)
    if e.status == "read" then return _("Read") end
    if e.status == "reading" then return T(_("%1%"), e.pct or 0) end
    return _("Unread")
end

local function entryTitle(e)
    local title = e.date or e.base
    if e.planday then
        title = title .. "  ·  " .. T(_("Day %1"), e.planday)
    end
    return title
end

-- EPUB title from CoverBrowser's cached book info, if already indexed (no extraction).
local function cachedBookTitle(file)
    local ok, BIM = pcall(require, "bookinfomanager")
    if not ok or type(BIM) ~= "table" or not BIM.getBookInfo then return nil end
    local ok2, info = pcall(BIM.getBookInfo, BIM, file, false)
    if ok2 and type(info) == "table" and type(info.title) == "string" and info.title ~= "" then
        return info.title
    end
end

local function rowText(e)
    local text = entryTitle(e)
    local book_title = cachedBookTitle(e.file)
    if book_title then text = text .. "  ·  " .. book_title end
    return text
end

function Devotional:buildItems()
    local entries, folder_ok = self:scan()
    self.entries = entries
    local items = {}
    items[#items + 1] = {
        text = _("Sync now"),
        bold = true,
        callback = function() self:sync() end,
    }
    if not folder_ok then
        items[#items + 1] = {
            text = T(_("Folder not found: %1\nTap Sync now to create it and download."), DEVO_DIR),
            select_enabled = false,
        }
        return items
    end
    if #entries == 0 then
        items[#items + 1] = { text = _("No devotionals yet. Tap Sync now."), select_enabled = false }
        return items
    end
    -- newest unread = first (newest) entry that is not read
    for _i, e in ipairs(entries) do
        if e.status ~= "read" then
            items[#items + 1] = {
                text = T(_("Newest unread: %1"), entryTitle(e)),
                select_enabled = false,
            }
            break
        end
    end
    for _i, e in ipairs(entries) do
        items[#items + 1] = {
            text = rowText(e),
            mandatory = statusText(e),
            entry = e,
            callback = function() self:open(e) end,
        }
    end
    return items
end

-- ---------------------------------------------------------------------------
-- Zen UI integration (all runtime, no Zen files edited; every step is pcall'd
-- and any failure falls back to the plain KOReader Menu below).
-- ---------------------------------------------------------------------------

local function zenPlugin()
    local p = rawget(_G, "__ZEN_UI_PLUGIN")
    if type(p) == "table" and type(p.config) == "table" then return p end
end

-- Id of the Zen custom navbar tab bound to our Dispatcher action (e.g. "ct_1").
local function findZenTabId(zp)
    local nav = zp.config.navbar
    if type(nav) ~= "table" or type(nav.custom_tabs) ~= "table" then return nil end
    if type(nav.show_tabs) ~= "table" then return nil end
    for _i, ct in ipairs(nav.custom_tabs) do
        if type(ct) == "table" and type(ct.action) == "table" and ct.action.devotional_show
                and type(ct.id) == "string" and nav.show_tabs[ct.id] == true then
            return ct.id
        end
    end
end

-- Zen decides which Menus get the navbar in its patched Menu:init (navbar.lua:1456 Menu:init, 1424-1431 isStandaloneNavbarView):
-- a Menu with covers_fullscreen + is_borderless + title_bar_fm_style and no name is a
-- "standalone view" (navbar.lua:1428), and Zen then schedules injectStandaloneNavbar for
-- it if getRakuyomi().getStandaloneTabId(menu) returns a tab id (navbar.lua:1475-1485, injectStandaloneNavbar = navbar.lua:1869,
-- getRakuyomi = navbar.lua:30). That table is an extension point read with rawget on
-- every call, so we wrap its getStandaloneTabId in place (idempotent, chains the original).
local function installZenTabHook(tab_id)
    local R = rawget(_G, "__ZEN_UI_RAKUYOMI")
    if type(R) ~= "table" then
        R = {}
        _G.__ZEN_UI_RAKUYOMI = R
    end
    R._devotional_tab_id = tab_id
    if R._devotional_hooked then return end
    R._devotional_hooked = true
    local orig = R.getStandaloneTabId
    R.getStandaloneTabId = function(widget, ...)
        if type(widget) == "table" and widget._devotional_view then
            return R._devotional_tab_id
        end
        if orig then return orig(widget, ...) end
    end
end

-- Returns a Zen-styled standalone Menu, or nil, err.
function Devotional:buildZenMenu()
    local zp = zenPlugin()
    if not zp then return nil, "no zen" end
    local features = zp.config.features
    if type(features) ~= "table" or features.navbar ~= true then return nil, "navbar off" end
    local tab_id = findZenTabId(zp)
    if not tab_id then return nil, "no devotional tab" end
    local StandalonePage = require("modules/filebrowser/patches/standalone_page")
    local SharedState = require("common/shared_state")
    installZenTabHook(tab_id)

    local plugin = self
    local menu = StandalonePage.create_menu{
        title = " ",
        item_table = self:buildItems(),
        onMenuSelect = function(_menu_self, item)
            if item and item.callback then item.callback() end
        end,
        onMenuHold = function(_menu_self, item)
            if item and item.entry then plugin:holdDialog(item.entry) end
            return true
        end,
    }
    menu._devotional_view = true
    StandalonePage.hide_page_arrow(menu)
    StandalonePage.suppress_page_info_tap(menu)
    menu.close_callback = function()
        UIManager:close(menu)
        if plugin.menu == menu then plugin.menu = nil end
    end
    local orig_close_widget = menu.onCloseWidget
    menu.onCloseWidget = function(m, ...)
        if orig_close_widget then orig_close_widget(m, ...) end
        if plugin.menu == m then plugin.menu = nil end
    end
    -- Zen-style header: its status row (clock/battery) with a back chevron.
    pcall(StandalonePage.apply_status_row, menu, {
        createStatusRow = SharedState.get(zp, "createStatusRow"),
        createStatusRowCustomBack = SharedState.get(zp, "createStatusRowCustomBack"),
        repaintTitleBar = SharedState.get(zp, "repaintTitleBar"),
        label = _("Devotional"),
        back_callback = menu.close_callback,
    })
    return menu
end

function Devotional:buildPlainMenu()
    local plugin = self
    local DevoMenu = Menu:extend{}
    function DevoMenu:onMenuHold(item)
        if item.entry then plugin:holdDialog(item.entry) end
        return true
    end
    function DevoMenu:onCloseWidget()
        Menu.onCloseWidget(self)
        if plugin.menu == self then plugin.menu = nil end
    end
    return DevoMenu:new{
        title = _("Devotional"),
        item_table = self:buildItems(),
        is_borderless = true,
        is_popout = false,
        covers_fullscreen = true,
        width = Screen:getWidth(),
        height = Screen:getHeight(),
    }
end

function Devotional:show()
    if self.menu then
        UIManager:close(self.menu)
        self.menu = nil
    end
    local menu
    local ok, res, err = pcall(self.buildZenMenu, self)
    if ok and res then
        menu = res
    else
        logger.info("devotional: Zen view unavailable, using plain menu:", ok and err or res)
    end
    menu = menu or self:buildPlainMenu()
    self.menu = menu
    UIManager:show(menu)
end

function Devotional:refresh()
    if self.menu then
        self.menu:switchItemTable(nil, self:buildItems())
    end
end

function Devotional:open(e)
    local ok, ReaderUI = pcall(require, "apps/reader/readerui")
    if not ok then
        UIManager:show(InfoMessage:new{ text = _("Could not open the reader.") })
        return
    end
    if self.menu then
        UIManager:close(self.menu)
        self.menu = nil
    end
    ReaderUI:showReader(e.file)
end

function Devotional:holdDialog(e)
    local dialog
    local is_read = e.status == "read"
    dialog = ButtonDialog:new{
        title = entryTitle(e),
        title_align = "center",
        buttons = {
            {{
                text = is_read and _("Mark as unread") or _("Mark as read"),
                callback = function()
                    UIManager:close(dialog)
                    self:setRead(e, not is_read)
                end,
            }},
            {{
                text = _("Delete"),
                callback = function()
                    UIManager:close(dialog)
                    self:confirmDelete(e)
                end,
            }},
        },
    }
    UIManager:show(dialog)
end

function Devotional:setRead(e, read)
    local ok, err = pcall(function()
        local ds = DocSettings:open(e.file)
        local summary = ds:readSetting("summary") or {}
        if read then
            summary.status = "complete"
        else
            summary.status = "reading"
            ds:saveSetting("percent_finished", 0)
        end
        summary.modified = os.date("%Y-%m-%d", os.time())
        ds:saveSetting("summary", summary)
        ds:flush()
    end)
    BookList.resetBookInfoCache(e.file)
    if not ok then
        logger.warn("devotional: setRead failed", err)
        UIManager:show(InfoMessage:new{ text = _("Could not update status.") })
    end
    self:refresh()
end

function Devotional:confirmDelete(e)
    UIManager:show(ConfirmBox:new{
        text = T(_("Delete this devotional?\n\n%1\n\nIt can be downloaded again by Sync, as long as it is still in Dropbox."), entryTitle(e)),
        ok_text = _("Delete"),
        ok_callback = function()
            local ok, FileManager = pcall(require, "apps/filemanager/filemanager")
            local done
            if ok and FileManager and FileManager.deleteFile then
                done = FileManager:deleteFile(e.file, true)
            else
                done = os.remove(e.file)
                BookList.resetBookInfoCache(e.file)
                DocSettings.updateLocation(e.file)
            end
            if not done then
                UIManager:show(InfoMessage:new{ text = _("Could not delete the file.") })
            end
            self:refresh()
        end,
    })
end

local function listNames()
    local set, n = {}, 0
    if lfs.attributes(DEVO_DIR, "mode") == "directory" then
        for f in lfs.dir(DEVO_DIR) do
            if f:lower():match("%.epub$") then set[f] = true; n = n + 1 end
        end
    end
    return set, n
end

-- Finds the configured cloud storage server and runs KOReader's own
-- "Synchronize now" for it (CloudStorage:synchronizeCloud).
function Devotional:sync()
    NetworkMgr:runWhenOnline(function()
        self:doSync()
    end)
end

function Devotional:doSync()
    local ok_cs, CloudStorage = pcall(require, "apps/cloudstorage/cloudstorage")
    if not ok_cs then
        UIManager:show(InfoMessage:new{ text = _("Cloud storage is not available in this KOReader.") })
        return
    end
    local ok, cs = pcall(function() return CloudStorage:new{} end)
    if not ok or not cs or not cs.item_table then
        UIManager:show(InfoMessage:new{ text = _("Could not read the cloud storage settings.") })
        return
    end
    local item
    for _i, it in ipairs(cs.item_table) do
        if it.text == SERVER_NAME then item = it break end
    end
    if not item then
        UIManager:show(InfoMessage:new{
            text = T(_("Cloud storage server \"%1\" not found.\nAdd it under Cloud storage, with a Dropbox sync folder set."), SERVER_NAME),
        })
        return
    end
    if item.type ~= "dropbox" or not item.sync_source_folder or not item.sync_dest_folder then
        UIManager:show(InfoMessage:new{
            text = T(_("Server \"%1\" has no sync folders set.\nOpen Cloud storage, long-press it, and use Synchronize settings."), SERVER_NAME),
        })
        return
    end
    if lfs.attributes(item.sync_dest_folder, "mode") ~= "directory" then
        pcall(lfs.mkdir, item.sync_dest_folder)
    end

    local before = listNames()
    local plugin = self
    local orig = cs.downloadListFiles
    -- Wrap the download step only to know when it finished.
    cs.downloadListFiles = function(this, it)
        local downloaded, failed = orig(this, it)
        -- KOReader shows its own result message for ~3s; follow up after it.
        UIManager:scheduleIn(3.5, function()
            local after, n_after = listNames()
            local added = 0
            for f in pairs(after) do
                if not before[f] then added = added + 1 end
            end
            plugin:refresh()
            local text
            if added == 0 then
                text = _("No new devotionals")
            elseif added == 1 then
                text = _("1 new devotional")
            else
                text = T(_("%1 new devotionals"), added)
            end
            UIManager:show(Notification:new{ text = text })
        end)
        return downloaded, failed
    end
    local ok_run, err = pcall(cs.synchronizeCloud, cs, item)
    if not ok_run then
        logger.warn("devotional: sync failed", err)
        UIManager:show(InfoMessage:new{ text = _("Sync failed. Check your connection and Dropbox settings.") })
    end
end

return Devotional
