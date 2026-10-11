"""Keep the two contractually array-valued fields stable on Redis Lua cjson."""
ENCODE = r'''
local function encode_plan(value)
    local raw = cjson.encode(value)
    -- cjson versions including Redis 3 serialize empty tables as objects.
    -- Only schema field values are changed; quoted user text is JSON escaped.
    raw = string.gsub(raw,'"tasks":{}','"tasks":[]')
    raw = string.gsub(raw,'"completed":{}','"completed":[]')
    return raw
end
'''
