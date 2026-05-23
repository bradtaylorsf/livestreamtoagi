export default {
    name: '!goToPlace',
    aliases: ['!goto', "!walkToPlace"],
    description: "Go to a named place.",
    params: {
        place_name: {
            type: 'string',
            description: 'Name of the saved place.',
        },
        arrive_within_blocks: {
            type: 'float',
            description: 'Required arrival radius.',
        },
        safe_mode: {
            type: 'boolean',
            optional: true,
            description: 'Avoid digging or risky movement while traveling.',
        },
    },
    perform: async function (agent, place_name, arrive_within_blocks, safe_mode) {
        return `${agent.name}:${place_name}:${arrive_within_blocks}:${safe_mode}`;
    },
};
