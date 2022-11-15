from flask import Flask, request, Response
from werkzeug.exceptions import BadRequest
import json
import re


class ScoresServer:
    def __init__(self, host: str, port: int, highscore_table_limit: int = 100000):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.highscore_table_limit = highscore_table_limit

        # use dicts for lookup as its O(1)
        # store both users and scores so you can lookup on either without iterating over all items in the dict
        self.scores = dict() # {25:"bob"}
        self.users = dict() # {"dave":3}

        @self.app.route('/scores/', methods=['GET', 'POST'])
        def __scores():
            if request.method == "POST":
                return self.add_score()
            else: # request.method == "GET"
                return self.get_all_scores()

        @self.app.route('/scores/<int:rank>/', methods=['GET'])
        def __get_rank(rank):
            return self.get_rank(rank)

    def validate(self, end_point_config: dict):
        """
        Takes in a dict config object that has the attributes of the endpoint.
        Will validate them to check they:
            1 - correct json
            2 - all required fields are present in the request
            3 - all fields are the correct types

        this could also be used to check for other factors such as length to avoid any DB related insertion errors
        but I have not done this here as is not needed


        :param end_point_config: dict of request attributes
        :return: flask.Response or None
        """
        if request.is_json:
            try:
                req = request.get_json()
            except BadRequest as e:
                print(f"BadRequest error: {e}")
                resp = {
                    "status": "failed",
                    "message": "request must be valid json"
                }
                return Response(json.dumps(resp), status=400, mimetype='application/json')

            for param, info in end_point_config.items():
                req_param = req.get(param)
                if req_param is None:
                    print(f"{param} is not present in the request and its required")
                    resp = {
                        "status": "failed",
                        "message": f"{param} is not present in the request and its required"
                    }
                    return Response(json.dumps(resp), status=400, mimetype='application/json')

                if not isinstance(req_param, eval(info['type'])):

                    print(f"{param} is not the correct type, must be {info['type']}")
                    resp = {
                        "status": "failed",
                        "message": f"{param} is not the correct type, must be {info['type']}"
                    }
                    return Response(json.dumps(resp), status=400, mimetype='application/json')

                regex = info.get('regex')
                # may not always want to do a regex check for every parameter
                if regex is not None:
                    print("req param = ", req_param)
                    result = re.match(regex['pattern'], str(req_param))
                    print("results = ", result)
                    if not result:
                        resp = {
                            "status": "failed",
                            "message": regex['error_msg']
                        }
                        return Response(json.dumps(resp), status=400, mimetype='application/json')
            # means the post request has been validated successfully
            return None
        else:
            resp = {
                "status": "failed",
                "message": "request must be valid json"
            }
            return Response(json.dumps(resp), status=400, mimetype='application/json')

    def add_score(self):
        """
        Checks to see if the user or score already exist.
        If the score exists, check to see if it is the current user who has it and send custom message depending
        on answer.

        If user has a score that is already higher then leave that score in place.
        If the users score is higher replace it.


        :return: flask.Response
        """
        # ideally this dict would come from a config file for all endpoints on the api
        # as only one post endpoint have just hardcoded it
        end_point_config = {
            "name": {
                "type": "str",
                "regex": {
                    "pattern": "^[a-z]+$",
                    "error_msg": "name string must be lowercase and only contain the characters a-z"
                },
                "length": 50
            },
            "score": {
                "type": "int",
                "regex": {
                    "pattern": "^[1-9]\d*$",
                    "error_msg": "score must be a positive integer and greater than 0"
                },
                "length": 20
            }
        }
        error_response = self.validate(end_point_config)
        if error_response is not None:
            return error_response

        req = request.get_json()
        name = req['name']
        score = req['score']
        prev_score = self.users.get(name)
        user = self.scores.get(score)
        if user is not None and user != name:
            resp = {
                "status": "success",
                "message": f"user {user} already has this highscore and you haven't beaten it, better luck next time!",
                "score": {"user": user, "score": score}
            }
            return Response(json.dumps(resp), status=200, mimetype='application/json')

        extra_msg = ""
        if prev_score:
            print(f"user already exists with a high score of {prev_score}")
            if score > prev_score:
                # remove them both from the list
                extra_msg = f", this is higher than their previous of {prev_score}"
                del self.users[name]
                del self.scores[prev_score]
            else:
                resp = {
                    "status": "success",
                    "message": f"user {name} has not beaten their previous highscore!",
                    "score": {"user": name, "score": prev_score}
                }
                return Response(json.dumps(resp), status=200, mimetype='application/json')

        if len(self.scores) == self.highscore_table_limit:
            # if scores are full then need to remove the lowest
            lowest_highscore = list(self.scores)[-1]
            if lowest_highscore > score:
                resp = {
                    "status": "success",
                    "message": f"Looks like you didn't get high enough to be on the leaderboards, you must be within "
                               f"the top {self.highscore_table_limit} users, you must beat {lowest_highscore}",
                }
                return Response(json.dumps(resp), status=200, mimetype='application/json')

            # means they beat the lowest user so need to kick them out
            lowest_user = self.scores.get(lowest_highscore)
            del self.users[lowest_user]
            del self.scores[lowest_highscore]
            print(f"removed user {lowest_user} with score {lowest_highscore} from the leadeboard")

        self.users[name] = score
        self.scores[score] = name
        self.sort_scores()

        resp = {
              "status": "success",
              "message": f"added score of {score} for {name}{extra_msg}",
              "score": {"user": name, "score": score}
              }
        return Response(json.dumps(resp), status=200, mimetype='application/json')

    def sort_scores(self):
        """
        Sorts the scores dict inversely with the highest number at the top

        """
        # sorted uses Timsort algorithm O(n log n)
        self.scores = {k: self.scores[k] for k in sorted(self.scores, reverse=True)}

    def get_rank(self, rank):
        """
        Converts the scores dict into a list to allow accessing by index.
        subtract the rank by one to get the real index

        Will return a 404 not found response if the rank is not found in the scores list
        Otherwise returns a 200 ok with the

        :param rank: int
        :return: flask.Response
        """

        if rank <= 0:
            resp = {
                "status": "failed",
                "message": f"rank must be 1 or greater"
            }
            return Response(json.dumps(resp), status=404, mimetype='application/json')

        index = rank - 1
        score_list = list(self.scores)
        scores_length = len(score_list)
        if scores_length < rank:
            resp = {
                "status": "failed",
                "message": f"rank {rank} could not be found, there are only {scores_length} scores"
            }
            return Response(json.dumps(resp), status=404, mimetype='application/json')

        score = score_list[index]
        name = self.scores.get(score)
        resp = {
            "status": "success",
            "message": f"found user {name} at rank {rank} with a score of {score}",
            "score": {"user": name, "score": score}
        }
        return Response(json.dumps(resp), status=200, mimetype='application/json')

    def get_all_scores(self):
        """
        returns the entire list of scores ordered from largest to smallest
        :return: flask.Response
        """
        scores = {"status": "success",
                  "message": "retrieved all scores",
                  "scores": self.scores
                  }
        return Response(json.dumps(scores), status=200, mimetype='application/json')

    def run(self):
        self.app.run(host=self.host,
                     port=self.port,
                     debug=True
                     )


if __name__ == "__main__":
    server = ScoresServer('localhost', 8000,
                          highscore_table_limit=10
                          )
    server.run()
