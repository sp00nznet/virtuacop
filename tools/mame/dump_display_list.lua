local frame = 0
local mem = nil
local outdir = os.getenv("VCOP_DUMP_DIR") or "."
emu.register_frame(function()
    frame = frame + 1
    if not mem then
        local cpu = manager.machine.devices[":maincpu"]
        if cpu then mem = cpu.spaces["program"] end
    end
    if not mem then return end
    if frame >= 560 and frame <= 900 and (frame % 20) == 0 then
        local fh = io.open(string.format("%s/mp_%05d.buf", outdir, frame), "wb")
        if fh then
            for a = 0, 0x1FFFC, 4 do
                local v = mem:read_u32(0x00900000 + a)
                fh:write(string.char(v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF))
            end
            fh:close()
            manager.machine.video:snapshot()
            print("PAIR " .. frame)
        end
    end
end)
