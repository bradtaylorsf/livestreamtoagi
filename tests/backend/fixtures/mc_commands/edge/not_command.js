const helper = {
    name: '!helper',
    description: 'This object is not exported as a command.',
};

export function notACommand() {
    return helper;
}
